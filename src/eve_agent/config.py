"""
Configuration module (v2).

Loads .env via python-dotenv directly, then validates with pydantic.
This avoids pydantic-settings' env-file parsing which has been giving
us trouble with EVE-style secrets.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Project paths
# ---------------------------------------------------------------------------
PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]

DATA_DIR: Path = PROJECT_ROOT / "data"
LOGS_DIR: Path = DATA_DIR / "logs"
CACHE_DB_PATH: Path = DATA_DIR / "cache.sqlite"
SDE_DB_PATH: Path = DATA_DIR / "sde.sqlite"
TOKENS_PATH: Path = DATA_DIR / "tokens.json.enc"

ENV_FILE: Path = PROJECT_ROOT / ".env"


# Load .env into os.environ. override=True so .env wins over stale shell vars.
load_dotenv(ENV_FILE, override=True)


# ---------------------------------------------------------------------------
# ESI constants
# ---------------------------------------------------------------------------
ESI_BASE_URL: str = "https://esi.evetech.net/latest"
ESI_AUTH_URL: str = "https://login.eveonline.com/v2/oauth/authorize"
ESI_TOKEN_URL: str = "https://login.eveonline.com/v2/oauth/token"
ESI_VERIFY_URL: str = "https://login.eveonline.com/oauth/verify"
ESI_JWKS_URL: str = "https://login.eveonline.com/oauth/jwks"

DEFAULT_SCOPES: list[str] = [
    "esi-skills.read_skills.v1",
    "esi-skills.read_skillqueue.v1",
    "esi-wallet.read_character_wallet.v1",
    "esi-location.read_location.v1",
    "esi-location.read_ship_type.v1",
    "esi-location.read_online.v1",
    "esi-assets.read_assets.v1",
    "esi-characters.read_corporation_roles.v1",
    "esi-mail.read_mail.v1",
    "esi-markets.read_character_orders.v1",
    "esi-industry.read_character_jobs.v1",
    "esi-fittings.read_fittings.v1",
    "esi-contracts.read_character_contracts.v1",
]


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
class Settings(BaseModel):
    """Validated settings loaded from environment variables."""

    eve_client_id: str = Field(...)
    eve_client_secret: str = Field(...)
    eve_callback_url: str = Field(default="http://localhost:8765/callback")
    eve_user_agent: str = Field(...)

    @field_validator("eve_user_agent")
    @classmethod
    def user_agent_must_have_contact(cls, v: str) -> str:
        if "@" not in v and "(" not in v:
            raise ValueError(
                "EVE_USER_AGENT must include a contact (email or "
                "'name (contact)' format)."
            )
        return v

    @field_validator("eve_client_id", "eve_client_secret")
    @classmethod
    def not_placeholder(cls, v: str, info) -> str:
        if v.startswith("your_") and v.endswith("_here"):
            raise ValueError(
                f"{info.field_name} is still set to the placeholder. "
                f"Edit .env with real EVE app credentials."
            )
        return v


def _read_setting(name: str) -> str:
    """Read a single env var with a clear error if missing."""
    val = os.environ.get(name)
    if val is None or val == "":
        raise RuntimeError(
            f"{name} is not set. Check your .env file at {ENV_FILE} "
            f"or set the variable in your shell."
        )
    return val.strip()


# Build settings explicitly from os.environ — bypasses pydantic-settings.
settings = Settings(
    eve_client_id=_read_setting("EVE_CLIENT_ID"),
    eve_client_secret=_read_setting("EVE_CLIENT_SECRET"),
    eve_callback_url=os.environ.get(
        "EVE_CALLBACK_URL", "http://localhost:8765/callback"
    ).strip(),
    eve_user_agent=_read_setting("EVE_USER_AGENT"),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)


if __name__ == "__main__":
    ensure_dirs()
    print("Config loaded successfully.")
    print(f"  PROJECT_ROOT      = {PROJECT_ROOT}")
    print(f"  DATA_DIR          = {DATA_DIR}")
    print(f"  ENV_FILE          = {ENV_FILE}  (exists: {ENV_FILE.exists()})")
    print(f"  EVE_CLIENT_ID     = {settings.eve_client_id[:6]}... "
          f"({len(settings.eve_client_id)} chars)")
    print(f"  EVE_CLIENT_SECRET = ***hidden*** "
          f"({len(settings.eve_client_secret)} chars)")
    print(f"  EVE_CALLBACK_URL  = {settings.eve_callback_url}")
    print(f"  EVE_USER_AGENT    = {settings.eve_user_agent}")
    print(f"  DEFAULT_SCOPES    = {len(DEFAULT_SCOPES)} scopes configured")
