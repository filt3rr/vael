"""
Discord webhook alerts — Vael reaches you on your phone.

Configure by adding DISCORD_WEBHOOK_URL to your .env file.
Supports rich embeds with color-coded severity levels.

Usage:
    from eve_agent.discord_alerts import alert, alert_rich, test_webhook

    alert("Skill complete", "Navigation V finished training.")
    alert_rich("Market Alert", "Tritanium dropped 8% in Jita", color="warning",
               fields={"Old price": "4.08", "New price": "3.75"})
"""

from __future__ import annotations

import logging
import os
import time
from typing import Optional

import httpx
from dotenv import load_dotenv

from eve_agent.config import ENV_FILE


log = logging.getLogger(__name__)
load_dotenv(ENV_FILE, override=False)

WEBHOOK_URL: str = os.environ.get("DISCORD_WEBHOOK_URL", "")

COLORS = {
    "info":    0x5865F2,   # Discord blurple
    "success": 0x57F287,   # Green
    "warning": 0xFEE75C,   # Yellow
    "danger":  0xED4245,   # Red
    "market":  0x3B8BD4,   # Blue
    "intel":   0xE24B4A,   # Red/orange
    "skill":   0x9FE1CB,   # Teal
    "industry":0xEF9F27,   # Amber
    "neutral": 0x99AAB5,   # Gray
}


def _is_configured() -> bool:
    return bool(WEBHOOK_URL and WEBHOOK_URL.startswith("https://discord.com/api/webhooks/"))


def alert(title: str, message: str, color: str = "neutral") -> bool:
    """
    Send a simple Discord notification embed.
    Returns True on success, False on failure.
    """
    if not _is_configured():
        log.debug("Discord webhook not configured — skipping alert: %s", title)
        return False

    return alert_rich(title, message, color=color)


def alert_rich(
    title: str,
    description: str,
    color: str = "neutral",
    fields: Optional[dict] = None,
    footer: Optional[str] = None,
    url: Optional[str] = None,
) -> bool:
    """Send a rich Discord embed with optional fields and footer."""
    if not _is_configured():
        log.debug("Discord webhook not configured.")
        return False

    embed: dict = {
        "title": title,
        "description": description,
        "color": COLORS.get(color, COLORS["neutral"]),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    if url:
        embed["url"] = url
    if fields:
        embed["fields"] = [
            {"name": k, "value": str(v), "inline": True}
            for k, v in fields.items()
        ]
    if footer:
        embed["footer"] = {"text": footer}

    payload = {
        "username": "Vael",
        "avatar_url": "https://images.evetech.net/types/670/icon",
        "embeds": [embed],
    }

    try:
        resp = httpx.post(WEBHOOK_URL, json=payload, timeout=10)
        if resp.status_code in (200, 204):
            log.info("Discord alert sent: %s", title)
            return True
        log.warning("Discord webhook returned %d: %s", resp.status_code, resp.text[:200])
        return False
    except Exception as e:
        log.warning("Discord alert failed: %s", e)
        return False


def alert_market(item: str, event: str, details: dict) -> bool:
    """Convenience wrapper for market alerts."""
    fields = {k: str(v) for k, v in details.items()}
    return alert_rich(
        title=f"Market | {item}",
        description=event,
        color="market",
        fields=fields,
        footer="EVE Market Monitor",
    )


def alert_skill(skill_name: str, level: int) -> bool:
    """Convenience wrapper for skill completion alerts."""
    return alert_rich(
        title="Skill Training Complete",
        description=f"**{skill_name}** finished training to **Level {level}**.",
        color="skill",
        footer="EVE Skill Tracker",
    )


def alert_intel(system: str, event: str, danger: int) -> bool:
    """Convenience wrapper for intel/danger alerts."""
    color = "danger" if danger >= 7 else "warning" if danger >= 4 else "info"
    return alert_rich(
        title=f"Intel | {system}",
        description=event,
        color=color,
        fields={"Danger rating": f"{danger}/10"},
        footer="EVE Intel Monitor",
    )


def alert_industry(product: str, runs: int, event: str) -> bool:
    """Convenience wrapper for industry job alerts."""
    return alert_rich(
        title="Industry Job Complete",
        description=f"{runs}x **{product}** ready to deliver.",
        color="industry",
        footer="EVE Industry Tracker",
    )


def test_webhook() -> dict:
    """
    Send a test message to verify the webhook is configured correctly.
    Run: python -m eve_agent.discord_alerts
    """
    if not _is_configured():
        return {
            "status": "not_configured",
            "message": (
                "Add DISCORD_WEBHOOK_URL to your .env file.\n"
                "Get a webhook URL from: Discord server settings "
                "-> Integrations -> Webhooks -> New Webhook"
            ),
        }

    success = alert_rich(
        title="Vael Online",
        description="Discord alerts are configured and working. Vael will ping you here.",
        color="success",
        fields={
            "Status": "Connected",
            "Agent": "EVE Online MCP Agent",
        },
        footer="Test message",
    )
    return {
        "status": "success" if success else "failed",
        "webhook_configured": True,
    }


if __name__ == "__main__":
    import sys
    import json
    logging.basicConfig(level=logging.INFO)
    result = test_webhook()
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["status"] == "success" else 1)
