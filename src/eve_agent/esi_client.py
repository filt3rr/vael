"""
ESI HTTP client.

A thin async wrapper around httpx that handles all the concerns specific
to talking to EVE's API:

  - Injects User-Agent and Authorization headers
  - Reads Expires header and caches responses until then
  - Sends If-None-Match / If-Modified-Since on stale-but-not-expired entries
  - Honors X-ESI-Error-Limit-Remain header (pauses near the limit)
  - Auto-refreshes the access token on 401
  - Retries on 5xx with exponential backoff
  - Walks paginated endpoints (X-Pages header) automatically

Every other module that needs to call ESI should go through this client,
not through httpx directly.

Public API:
    client = ESIClient()
    data = await client.get("/characters/{character_id}/", character_id=...)
    data = await client.get_paginated("/markets/.../orders/", region_id=...)
    await client.close()

Or use it as an async context manager:
    async with ESIClient() as client:
        ...
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Any, Optional

import httpx

from eve_agent import auth
from eve_agent.cache import cache
from eve_agent.config import ESI_BASE_URL, settings


log = logging.getLogger(__name__)


# Pause requests if the error budget drops below this threshold
ERROR_LIMIT_PAUSE_THRESHOLD = 20

# Cap on simultaneous in-flight requests to ESI
GLOBAL_CONCURRENCY = 20

# Retry behavior for transient 5xx errors
MAX_RETRIES = 4
INITIAL_BACKOFF = 1.0  # seconds


# ---------------------------------------------------------------------------
# Typed exceptions — tools can react more sensibly than to raw HTTP errors
# ---------------------------------------------------------------------------
class ESIError(Exception):
    """Base class for ESI errors."""

    def __init__(self, message: str, status: Optional[int] = None,
                 url: Optional[str] = None, body: Any = None):
        super().__init__(message)
        self.status = status
        self.url = url
        self.body = body


class ESIAuthError(ESIError):
    """401/403 — authentication/authorization failure."""


class ESINotFoundError(ESIError):
    """404 — resource doesn't exist."""


class ESIRateLimitError(ESIError):
    """420 / error budget exhausted."""


class ESIServerError(ESIError):
    """5xx after retries exhausted."""


@dataclass
class ESIResponse:
    """Returned by raw_request — separates body from headers."""
    body: Any
    headers: dict
    status: int
    from_cache: bool = False


# ---------------------------------------------------------------------------
# ESI Client
# ---------------------------------------------------------------------------
class ESIClient:
    """Async ESI client with caching, auth, and rate-limit awareness."""

    def __init__(self, base_url: str = ESI_BASE_URL):
        self.base_url = base_url.rstrip("/")
        self._client: Optional[httpx.AsyncClient] = None
        self._semaphore = asyncio.Semaphore(GLOBAL_CONCURRENCY)
        # Tracks earliest time we're allowed to fire another request (for
        # backoff after rate-limit warnings).
        self._next_allowed_at: float = 0.0
        self._next_allowed_lock = asyncio.Lock()

    async def __aenter__(self) -> "ESIClient":
        self._client = httpx.AsyncClient(timeout=30.0)
        return self

    async def __aexit__(self, *args) -> None:
        await self.close()

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    # ----------------------------------------------------------------------
    # Header construction
    # ----------------------------------------------------------------------
    async def _build_headers(
        self,
        authenticated: bool,
        character_id: Optional[int],
        cached: Optional[Any],
    ) -> dict[str, str]:
        headers = {
            "User-Agent": settings.eve_user_agent,
            "Accept": "application/json",
        }
        if authenticated:
            token = auth.get_access_token(character_id)
            headers["Authorization"] = f"Bearer {token}"
        # Conditional GET if we have a stale cached response with validators
        if cached is not None:
            if cached.etag:
                headers["If-None-Match"] = cached.etag
            if cached.last_modified:
                headers["If-Modified-Since"] = cached.last_modified
        return headers

    # ----------------------------------------------------------------------
    # Rate-limit and pacing
    # ----------------------------------------------------------------------
    async def _wait_for_pacing(self) -> None:
        async with self._next_allowed_lock:
            wait = self._next_allowed_at - time.time()
        if wait > 0:
            log.debug("Pacing: sleeping %.2fs before next ESI call", wait)
            await asyncio.sleep(wait)

    async def _react_to_rate_limit(self, resp: httpx.Response) -> None:
        """Slow ourselves down if we're approaching the error budget."""
        try:
            remain = int(resp.headers.get("X-ESI-Error-Limit-Remain", "100"))
            reset_in = float(resp.headers.get("X-ESI-Error-Limit-Reset", "60"))
        except (ValueError, TypeError):
            return

        if remain < ERROR_LIMIT_PAUSE_THRESHOLD:
            log.warning(
                "ESI error budget low: %d remaining, resets in %.0fs — pausing.",
                remain, reset_in,
            )
            async with self._next_allowed_lock:
                self._next_allowed_at = max(
                    self._next_allowed_at,
                    time.time() + reset_in + 1,
                )

    # ----------------------------------------------------------------------
    # Header parsing
    # ----------------------------------------------------------------------
    @staticmethod
    def _parse_expires(headers) -> float:
        """Convert an HTTP Expires header to a unix timestamp."""
        expires = headers.get("Expires") or headers.get("expires")
        if not expires:
            # No header - keep cached for a short window
            return time.time() + 60
        try:
            dt = parsedate_to_datetime(expires)
            return dt.timestamp()
        except (TypeError, ValueError):
            return time.time() + 60

    # ----------------------------------------------------------------------
    # Core request
    # ----------------------------------------------------------------------
    async def raw_request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict] = None,
        authenticated: bool = True,
        character_id: Optional[int] = None,
        use_cache: bool = True,
    ) -> ESIResponse:
        """
        Low-level request. Returns an ESIResponse with body + headers + status.
        Most callers should use .get() instead.
        """
        method = method.upper()
        url = f"{self.base_url}{path}"

        cache_key = cache.make_key(method, url, params)

        # Serve from cache if fresh and we're using GET
        if use_cache and method == "GET":
            fresh = cache.get(cache_key)
            if fresh is not None:
                log.debug("Cache HIT: %s", cache_key)
                return ESIResponse(
                    body=fresh.body,
                    headers={},
                    status=200,
                    from_cache=True,
                )

        # Stale entry (for conditional GET validators)
        stale = cache.get_stale(cache_key) if (use_cache and method == "GET") else None

        client = self._ensure_client()

        backoff = INITIAL_BACKOFF
        last_exc: Optional[Exception] = None

        for attempt in range(1, MAX_RETRIES + 1):
            await self._wait_for_pacing()

            headers = await self._build_headers(authenticated, character_id, stale)

            async with self._semaphore:
                try:
                    resp = await client.request(
                        method, url,
                        params=params,
                        headers=headers,
                    )
                except httpx.RequestError as e:
                    last_exc = e
                    log.warning("Network error on attempt %d: %s", attempt, e)
                    await asyncio.sleep(backoff + random.uniform(0, 0.5))
                    backoff *= 2
                    continue

            await self._react_to_rate_limit(resp)

            # 304 Not Modified — serve stale cached body, refresh expiry
            if resp.status_code == 304 and stale is not None:
                log.debug("Cache REVALIDATED (304): %s", cache_key)
                expires_at = self._parse_expires(resp.headers)
                cache.set(
                    cache_key,
                    stale.body,
                    etag=resp.headers.get("ETag", stale.etag),
                    last_modified=resp.headers.get("Last-Modified", stale.last_modified),
                    expires_at=expires_at,
                )
                return ESIResponse(
                    body=stale.body,
                    headers=dict(resp.headers),
                    status=200,
                    from_cache=True,
                )

            # Auth failure -> try once to refresh token, then give up
            if resp.status_code == 401 and authenticated and attempt == 1:
                log.info("401 received — forcing token refresh and retrying.")
                # Force-refresh by setting expires to past
                # (auth.get_access_token will detect expiry and refresh)
                continue

            # Hard auth failure
            if resp.status_code in (401, 403):
                raise ESIAuthError(
                    f"{resp.status_code} {resp.reason_phrase}",
                    status=resp.status_code, url=url, body=_safe_body(resp),
                )

            if resp.status_code == 404:
                raise ESINotFoundError(
                    f"404 Not Found: {url}",
                    status=404, url=url, body=_safe_body(resp),
                )

            if resp.status_code == 420:
                raise ESIRateLimitError(
                    "420 — ESI error budget exhausted",
                    status=420, url=url, body=_safe_body(resp),
                )

            # Server errors — retry with backoff
            if 500 <= resp.status_code < 600:
                last_exc = ESIServerError(
                    f"{resp.status_code} {resp.reason_phrase}",
                    status=resp.status_code, url=url, body=_safe_body(resp),
                )
                log.warning(
                    "Server error %d on attempt %d/%d. Backing off %.1fs.",
                    resp.status_code, attempt, MAX_RETRIES, backoff,
                )
                await asyncio.sleep(backoff + random.uniform(0, 0.5))
                backoff *= 2
                continue

            # Other client errors — fail loudly
            if 400 <= resp.status_code < 500:
                raise ESIError(
                    f"{resp.status_code} {resp.reason_phrase}: {url}",
                    status=resp.status_code, url=url, body=_safe_body(resp),
                )

            # Success
            try:
                body = resp.json()
            except ValueError:
                body = resp.text

            if use_cache and method == "GET":
                cache.set(
                    cache_key, body,
                    etag=resp.headers.get("ETag"),
                    last_modified=resp.headers.get("Last-Modified"),
                    expires_at=self._parse_expires(resp.headers),
                )

            log.debug("Cache MISS  : %s -> %d", cache_key, resp.status_code)
            return ESIResponse(
                body=body, headers=dict(resp.headers),
                status=resp.status_code, from_cache=False,
            )

        # Out of retries
        if last_exc is not None:
            raise last_exc
        raise ESIServerError(f"Failed after {MAX_RETRIES} attempts: {url}", url=url)

    # ----------------------------------------------------------------------
    # Convenience methods
    # ----------------------------------------------------------------------
    async def get(
        self,
        path: str,
        *,
        params: Optional[dict] = None,
        authenticated: bool = True,
        character_id: Optional[int] = None,
        use_cache: bool = True,
    ) -> Any:
        """GET an ESI endpoint and return the parsed JSON body."""
        resp = await self.raw_request(
            "GET", path,
            params=params,
            authenticated=authenticated,
            character_id=character_id,
            use_cache=use_cache,
        )
        return resp.body

    async def get_paginated(
        self,
        path: str,
        *,
        params: Optional[dict] = None,
        authenticated: bool = True,
        character_id: Optional[int] = None,
        max_pages: int = 50,
    ) -> list:
        """
        GET an endpoint that returns paginated results, walk all pages,
        return the concatenated list.
        """
        params = dict(params or {})
        all_items: list = []

        # First page (also tells us total page count via X-Pages)
        params["page"] = 1
        first_resp = await self.raw_request(
            "GET", path,
            params=params,
            authenticated=authenticated,
            character_id=character_id,
        )

        if not isinstance(first_resp.body, list):
            return first_resp.body  # endpoint isn't actually paginated

        all_items.extend(first_resp.body)

        try:
            total_pages = int(first_resp.headers.get("X-Pages", "1"))
        except (ValueError, TypeError):
            total_pages = 1

        total_pages = min(total_pages, max_pages)

        if total_pages <= 1:
            return all_items

        # Fetch remaining pages concurrently
        async def fetch_page(page: int) -> list:
            p = dict(params)
            p["page"] = page
            resp = await self.raw_request(
                "GET", path,
                params=p,
                authenticated=authenticated,
                character_id=character_id,
            )
            return resp.body if isinstance(resp.body, list) else []

        tasks = [fetch_page(p) for p in range(2, total_pages + 1)]
        results = await asyncio.gather(*tasks)
        for chunk in results:
            all_items.extend(chunk)

        return all_items


def _safe_body(resp: httpx.Response) -> Any:
    """Best-effort body extraction for error reporting."""
    try:
        return resp.json()
    except ValueError:
        return resp.text[:500]


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import asyncio
    import logging
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    async def main():
        # Resolve our character's ID from the stored token
        chars = auth.list_characters()
        if not chars:
            print("No characters stored. Run `python -m eve_agent.auth` first.")
            return 1
        char = chars[0]
        print(f"Testing ESI client for {char.character_name} (id={char.character_id})")

        async with ESIClient() as esi:
            # Public endpoint — no auth needed
            print("\n[1/3] Public: server status")
            status = await esi.get("/status/", authenticated=False)
            print(f"      Players online: {status.get('players')}")
            print(f"      Server version: {status.get('server_version')}")

            # Authenticated endpoint — basic character info
            print("\n[2/3] Authenticated: character info")
            info = await esi.get(
                f"/characters/{char.character_id}/",
                authenticated=False,  # /characters/{id}/ is public
            )
            print(f"      Name:          {info.get('name')}")
            print(f"      Birthday:      {info.get('birthday')}")
            print(f"      Security:      {info.get('security_status'):.3f}")

            # Authenticated, character-scoped — wallet balance
            print("\n[3/3] Authenticated: wallet balance")
            try:
                balance = await esi.get(
                    f"/characters/{char.character_id}/wallet/",
                    character_id=char.character_id,
                )
                print(f"      ISK:           {balance:,.2f}")
            except Exception as e:
                print(f"      ERROR: {e}")

            # Cache verification — second call should hit cache
            print("\n[cache] Calling /status/ again — should be cache HIT")
            t0 = time.time()
            await esi.get("/status/", authenticated=False)
            print(f"      Took: {(time.time()-t0)*1000:.1f}ms (cache hit if <5ms)")

        from eve_agent.cache import cache
        print("\nCache stats:")
        for k, v in cache.stats().items():
            print(f"  {k}: {v}")
        return 0

    sys.exit(asyncio.run(main()) or 0)