"""
EVE SSO authentication.

Implements the OAuth2 Authorization Code flow with PKCE against EVE's
SSO endpoints, plus encrypted refresh-token storage and automatic
access-token refresh.

Public API:
    login() -> CharacterToken
        Run the interactive browser-based login. Saves an encrypted
        token bundle to data/tokens.json.enc. Returns the result.

    get_access_token(character_id: int | None = None) -> str
        Return a fresh access token for the requested character
        (or the only stored character if not specified). Refreshes
        automatically if expired.

    list_characters() -> list[CharacterToken]
        Return metadata for all stored characters (no secrets).

    logout(character_id: int | None = None) -> None
        Remove stored tokens for one (or all) characters.

CLI:
    python -m eve_agent.auth              # interactive login
    python -m eve_agent.auth --list       # list stored characters
    python -m eve_agent.auth --logout     # delete all stored tokens
    python -m eve_agent.auth --refresh    # force-refresh access token
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.server
import json
import logging
import secrets
import socketserver
import sys
import threading
import time
import urllib.parse
import webbrowser
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

import httpx
import keyring
from cryptography.fernet import Fernet, InvalidToken

from eve_agent.config import (
    DEFAULT_SCOPES,
    ESI_AUTH_URL,
    ESI_TOKEN_URL,
    ESI_VERIFY_URL,
    TOKENS_PATH,
    ensure_dirs,
    settings,
)


log = logging.getLogger(__name__)

# Keyring service/account names. Storing the Fernet key in the OS keyring
# rather than on disk means even an attacker with read access to the project
# folder can't decrypt the refresh tokens.
KEYRING_SERVICE = "eve-agent"
KEYRING_ACCOUNT = "token-encryption-key"

# How early before expiry we proactively refresh (seconds).
REFRESH_LEEWAY = 60


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------
@dataclass
class CharacterToken:
    character_id: int
    character_name: str
    access_token: str
    refresh_token: str
    expires_at: float           # unix timestamp
    scopes: list[str]
    token_type: str = "Bearer"

    def is_expired(self, leeway: float = REFRESH_LEEWAY) -> bool:
        return time.time() + leeway >= self.expires_at

    def public_dict(self) -> dict:
        """Safe to log/print (no secrets)."""
        return {
            "character_id": self.character_id,
            "character_name": self.character_name,
            "expires_at": self.expires_at,
            "scopes": self.scopes,
            "token_type": self.token_type,
        }


# ---------------------------------------------------------------------------
# Encryption key management (OS keyring)
# ---------------------------------------------------------------------------
def _get_or_create_fernet() -> Fernet:
    """Get the encryption key from OS keyring, generating one on first use."""
    key = keyring.get_password(KEYRING_SERVICE, KEYRING_ACCOUNT)
    if key is None:
        key = Fernet.generate_key().decode("ascii")
        keyring.set_password(KEYRING_SERVICE, KEYRING_ACCOUNT, key)
        log.info("Generated new token-encryption key and stored in OS keyring.")
    return Fernet(key.encode("ascii"))


# ---------------------------------------------------------------------------
# Encrypted token storage
# ---------------------------------------------------------------------------
def _load_all_tokens() -> dict[int, CharacterToken]:
    """Load and decrypt all stored character tokens."""
    if not TOKENS_PATH.exists():
        return {}

    fernet = _get_or_create_fernet()
    try:
        encrypted = TOKENS_PATH.read_bytes()
        plaintext = fernet.decrypt(encrypted)
    except InvalidToken:
        log.error(
            "Could not decrypt %s — encryption key in OS keyring does not "
            "match. If you regenerated keyring entries, you'll need to "
            "delete tokens.json.enc and re-login.",
            TOKENS_PATH,
        )
        return {}

    raw: dict[str, dict] = json.loads(plaintext)
    return {int(cid): CharacterToken(**rec) for cid, rec in raw.items()}


def _save_all_tokens(tokens: dict[int, CharacterToken]) -> None:
    """Encrypt and write all character tokens to disk."""
    ensure_dirs()
    fernet = _get_or_create_fernet()
    payload = {str(cid): asdict(tok) for cid, tok in tokens.items()}
    plaintext = json.dumps(payload, indent=2).encode("utf-8")
    encrypted = fernet.encrypt(plaintext)
    TOKENS_PATH.write_bytes(encrypted)
    log.info("Saved %d character token(s) to %s", len(tokens), TOKENS_PATH)


def _save_one_token(tok: CharacterToken) -> None:
    """Add or update a single character's token bundle."""
    all_tokens = _load_all_tokens()
    all_tokens[tok.character_id] = tok
    _save_all_tokens(all_tokens)


# ---------------------------------------------------------------------------
# PKCE helpers
# ---------------------------------------------------------------------------
def _make_pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge). EVE requires PKCE."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode()
    challenge_bytes = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(challenge_bytes).rstrip(b"=").decode()
    return verifier, challenge


# ---------------------------------------------------------------------------
# Local callback HTTP server
# ---------------------------------------------------------------------------
class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    """Catches the redirect from EVE SSO and stores the auth code."""

    # Filled in by the launcher before the server starts.
    expected_state: str = ""
    captured: dict[str, str] = {}

    # Silence default access logging.
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return

        params = dict(urllib.parse.parse_qsl(parsed.query))
        # Stash for the main thread to pick up.
        type(self).captured.update(params)

        # Render a friendly response in the browser.
        if "error" in params:
            body = (
                f"<html><body style='font-family:sans-serif;padding:2em;'>"
                f"<h1>Login failed</h1><p>EVE returned: "
                f"<code>{params.get('error')}</code></p>"
                f"<p>{params.get('error_description', '')}</p>"
                f"<p>You can close this tab.</p></body></html>"
            ).encode("utf-8")
        elif params.get("state") != type(self).expected_state:
            body = (
                b"<html><body style='font-family:sans-serif;padding:2em;'>"
                b"<h1>Login failed</h1><p>State mismatch -- possible CSRF "
                b"attempt. Try again.</p></body></html>"
            )
        else:
            body = (
                b"<html><body style='font-family:sans-serif;padding:2em;'>"
                b"<h1>Login successful</h1><p>You can close this tab and "
                b"return to your terminal.</p></body></html>"
            )

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _run_callback_server(expected_state: str, port: int) -> dict[str, str]:
    """
    Run a one-shot HTTP server that waits for the OAuth callback.

    Blocks until the callback arrives or 5 minutes pass.
    """
    _CallbackHandler.expected_state = expected_state
    _CallbackHandler.captured = {}

    # Allow address reuse so quick re-runs don't fail.
    socketserver.TCPServer.allow_reuse_address = True

    with socketserver.TCPServer(("127.0.0.1", port), _CallbackHandler) as httpd:
        # Run server on background thread so we can poll for completion.
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()

        deadline = time.time() + 300  # 5 minute timeout
        while time.time() < deadline:
            if _CallbackHandler.captured:
                # Give the server a tick to finish writing the response.
                time.sleep(0.2)
                httpd.shutdown()
                return dict(_CallbackHandler.captured)
            time.sleep(0.1)

        httpd.shutdown()
        raise TimeoutError("OAuth callback did not arrive within 5 minutes.")


# ---------------------------------------------------------------------------
# Token endpoint calls
# ---------------------------------------------------------------------------
def _basic_auth_header() -> dict[str, str]:
    """RFC6749 Basic auth using client_id:client_secret."""
    raw = f"{settings.eve_client_id}:{settings.eve_client_secret}"
    encoded = base64.b64encode(raw.encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {encoded}"}


def _exchange_code_for_token(code: str, code_verifier: str) -> dict:
    """Exchange the auth code (+ PKCE verifier) for tokens."""
    headers = {
        **_basic_auth_header(),
        "Content-Type": "application/x-www-form-urlencoded",
        "Host": "login.eveonline.com",
        "User-Agent": settings.eve_user_agent,
    }
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "code_verifier": code_verifier,
    }
    resp = httpx.post(ESI_TOKEN_URL, headers=headers, data=data, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _refresh_token(refresh_token: str) -> dict:
    """Use a refresh token to obtain a new access token."""
    headers = {
        **_basic_auth_header(),
        "Content-Type": "application/x-www-form-urlencoded",
        "Host": "login.eveonline.com",
        "User-Agent": settings.eve_user_agent,
    }
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    resp = httpx.post(ESI_TOKEN_URL, headers=headers, data=data, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _verify_character(access_token: str) -> dict:
    """Call /oauth/verify to retrieve character_id, name, and scopes."""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "User-Agent": settings.eve_user_agent,
    }
    resp = httpx.get(ESI_VERIFY_URL, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def login(scopes: Optional[list[str]] = None) -> CharacterToken:
    """Run the interactive browser login flow. Returns saved CharacterToken."""
    ensure_dirs()
    scopes = scopes or DEFAULT_SCOPES

    # PKCE + CSRF state
    code_verifier, code_challenge = _make_pkce_pair()
    state = secrets.token_urlsafe(24)

    # Parse port from configured callback URL
    cb = urllib.parse.urlparse(settings.eve_callback_url)
    port = cb.port or 8765

    # Build authorization URL
    auth_params = {
        "response_type": "code",
        "redirect_uri": settings.eve_callback_url,
        "client_id": settings.eve_client_id,
        "scope": " ".join(scopes),
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    auth_url = f"{ESI_AUTH_URL}?{urllib.parse.urlencode(auth_params)}"

    print()
    print("Opening EVE SSO in your browser...")
    print(f"If it doesn't open automatically, visit:\n  {auth_url}")
    print()
    webbrowser.open(auth_url)

    # Wait for callback
    callback = _run_callback_server(expected_state=state, port=port)

    if "error" in callback:
        raise RuntimeError(
            f"EVE SSO returned error: {callback['error']} — "
            f"{callback.get('error_description', '')}"
        )
    if callback.get("state") != state:
        raise RuntimeError("State mismatch on callback — aborting.")

    code = callback["code"]
    print("Received auth code. Exchanging for token...")

    token_response = _exchange_code_for_token(code, code_verifier)

    access_token = token_response["access_token"]
    refresh = token_response["refresh_token"]
    expires_in = token_response.get("expires_in", 1199)

    # Verify to get character info
    verify = _verify_character(access_token)
    char_id = int(verify["CharacterID"])
    char_name = verify["CharacterName"]
    granted_scopes = verify.get("Scopes", "").split() if verify.get("Scopes") else scopes

    tok = CharacterToken(
        character_id=char_id,
        character_name=char_name,
        access_token=access_token,
        refresh_token=refresh,
        expires_at=time.time() + expires_in,
        scopes=granted_scopes,
    )
    _save_one_token(tok)

    print()
    print(f"Authenticated as: {tok.character_name} (id={tok.character_id})")
    print(f"Scopes granted: {len(tok.scopes)}")
    print(f"Token saved to: {TOKENS_PATH}")
    return tok


def get_access_token(character_id: Optional[int] = None) -> str:
    """Return a fresh access token, refreshing if expired."""
    tokens = _load_all_tokens()
    if not tokens:
        raise RuntimeError(
            "No stored tokens. Run `python -m eve_agent.auth` to log in."
        )

    if character_id is None:
        if len(tokens) == 1:
            character_id = next(iter(tokens))
        else:
            ids = ", ".join(str(c) for c in tokens)
            raise RuntimeError(
                f"Multiple characters stored ({ids}). "
                f"Pass character_id explicitly."
            )

    if character_id not in tokens:
        raise RuntimeError(f"No stored token for character {character_id}.")

    tok = tokens[character_id]
    if not tok.is_expired():
        return tok.access_token

    log.info("Access token for %s expired; refreshing.", tok.character_name)
    refreshed = _refresh_token(tok.refresh_token)

    tok.access_token = refreshed["access_token"]
    tok.refresh_token = refreshed.get("refresh_token", tok.refresh_token)
    tok.expires_at = time.time() + refreshed.get("expires_in", 1199)
    _save_one_token(tok)
    return tok.access_token


def list_characters() -> list[CharacterToken]:
    """Return all stored character tokens (caller should not log secrets)."""
    return list(_load_all_tokens().values())


def logout(character_id: Optional[int] = None) -> None:
    """Remove stored tokens for one character (or all if not specified)."""
    if character_id is None:
        if TOKENS_PATH.exists():
            TOKENS_PATH.unlink()
            print(f"Removed {TOKENS_PATH}")
        else:
            print("No tokens stored.")
        return

    tokens = _load_all_tokens()
    if character_id in tokens:
        del tokens[character_id]
        _save_all_tokens(tokens)
        print(f"Removed token for character {character_id}.")
    else:
        print(f"No token stored for character {character_id}.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _cli() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m eve_agent.auth",
        description="EVE SSO authentication management.",
    )
    parser.add_argument("--list", action="store_true",
                        help="List stored characters")
    parser.add_argument("--logout", action="store_true",
                        help="Delete all stored tokens")
    parser.add_argument("--refresh", action="store_true",
                        help="Force-refresh access token for the stored character")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Verbose logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    try:
        if args.list:
            chars = list_characters()
            if not chars:
                print("No characters stored. Run without flags to log in.")
                return 0
            for c in chars:
                expires_in = max(0, int(c.expires_at - time.time()))
                print(f"  {c.character_id:>12}  {c.character_name}")
                print(f"     access token expires in: {expires_in}s")
                print(f"     scopes: {len(c.scopes)}")
            return 0

        if args.logout:
            logout()
            return 0

        if args.refresh:
            chars = list_characters()
            if not chars:
                print("No characters stored. Run without flags first.")
                return 1
            tok_str = get_access_token(chars[0].character_id)
            print(f"Refreshed. Access token length: {len(tok_str)} chars.")
            return 0

        # Default action: interactive login
        login()
        return 0

    except KeyboardInterrupt:
        print("\nAborted.")
        return 130
    except Exception as e:
        log.error("Auth failed: %s", e, exc_info=args.verbose)
        return 1


if __name__ == "__main__":
    sys.exit(_cli())
