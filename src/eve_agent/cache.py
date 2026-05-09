"""
Response cache for ESI calls.

A small SQLite-backed cache keyed by URL+params. Each entry stores:
- the response body (JSON-encoded)
- the response headers we care about (etag, last-modified, expires)
- the unix timestamp when the cache entry expires

ESI tells us how long it's safe to cache via the Expires response header
(or pages header for paginated endpoints). We honor that exactly — never
serve stale data, never re-fetch fresh data unnecessarily.

Public API:
    get(key) -> CachedResponse | None
    set(key, body, headers, expires_at)
    clear()
    stats() -> dict
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional

from eve_agent.config import CACHE_DB_PATH, ensure_dirs


_SCHEMA = """
CREATE TABLE IF NOT EXISTS esi_cache (
    cache_key      TEXT PRIMARY KEY,
    body_json      TEXT NOT NULL,
    etag           TEXT,
    last_modified  TEXT,
    expires_at     REAL NOT NULL,
    fetched_at     REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_expires_at ON esi_cache(expires_at);
"""


@dataclass
class CachedResponse:
    body: Any
    etag: Optional[str]
    last_modified: Optional[str]
    expires_at: float

    def is_fresh(self) -> bool:
        return time.time() < self.expires_at


class ResponseCache:
    """Thread-safe SQLite cache for ESI responses."""

    def __init__(self, db_path=CACHE_DB_PATH):
        ensure_dirs()
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        # check_same_thread=False because httpx may dispatch from various threads.
        # We serialize all writes with self._lock.
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript(_SCHEMA)

    @staticmethod
    def make_key(method: str, url: str, params: Optional[dict] = None) -> str:
        """Stable cache key for a request."""
        method = method.upper()
        if not params:
            return f"{method} {url}"
        # Sort params for deterministic keys
        sorted_params = "&".join(
            f"{k}={v}" for k, v in sorted(params.items()) if v is not None
        )
        return f"{method} {url}?{sorted_params}"

    def get(self, key: str) -> Optional[CachedResponse]:
        """Return a fresh cached response, or None if missing/expired."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT body_json, etag, last_modified, expires_at "
                "FROM esi_cache WHERE cache_key = ?",
                (key,),
            ).fetchone()

        if row is None:
            return None

        cached = CachedResponse(
            body=json.loads(row["body_json"]),
            etag=row["etag"],
            last_modified=row["last_modified"],
            expires_at=row["expires_at"],
        )
        return cached if cached.is_fresh() else None

    def get_stale(self, key: str) -> Optional[CachedResponse]:
        """Return a cached response even if expired (useful for ETag/304)."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT body_json, etag, last_modified, expires_at "
                "FROM esi_cache WHERE cache_key = ?",
                (key,),
            ).fetchone()
        if row is None:
            return None
        return CachedResponse(
            body=json.loads(row["body_json"]),
            etag=row["etag"],
            last_modified=row["last_modified"],
            expires_at=row["expires_at"],
        )

    def set(
        self,
        key: str,
        body: Any,
        etag: Optional[str] = None,
        last_modified: Optional[str] = None,
        expires_at: Optional[float] = None,
    ) -> None:
        """Insert or replace a cache entry."""
        if expires_at is None:
            # Default 60s if no expires header was provided.
            expires_at = time.time() + 60

        body_json = json.dumps(body)
        now = time.time()

        with self._lock, self._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO esi_cache
                    (cache_key, body_json, etag, last_modified, expires_at, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (key, body_json, etag, last_modified, expires_at, now),
            )
            conn.commit()

    def clear(self) -> int:
        """Delete all cache entries. Returns the number deleted."""
        with self._lock, self._conn() as conn:
            cursor = conn.execute("DELETE FROM esi_cache")
            conn.commit()
            return cursor.rowcount

    def stats(self) -> dict:
        """Return basic cache statistics."""
        now = time.time()
        with self._conn() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM esi_cache"
            ).fetchone()[0]
            fresh = conn.execute(
                "SELECT COUNT(*) FROM esi_cache WHERE expires_at > ?", (now,)
            ).fetchone()[0]
        return {
            "total_entries": total,
            "fresh_entries": fresh,
            "stale_entries": total - fresh,
            "db_path": str(self.db_path),
        }


# Module-level singleton.
cache = ResponseCache()


if __name__ == "__main__":
    # Quick self-test
    import pprint
    pprint.pprint(cache.stats())