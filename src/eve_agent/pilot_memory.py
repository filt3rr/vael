"""
Pilot memory — persistent cross-session storage for VAEL.

Stores goals, milestones, mistakes, market notes, skill plans,
and ISK history in a structured JSON file that persists between
Claude Desktop sessions.

Tools exposed:
    read_pilot_memory(category=None)
    write_pilot_memory(category, key, value)
    append_pilot_memory(category, entry)
    get_isk_history()
    log_isk_snapshot()
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from eve_agent.config import DATA_DIR, ensure_dirs


log = logging.getLogger(__name__)
MEMORY_PATH = DATA_DIR / "pilot_memory.json"

VALID_CATEGORIES = {
    "goals",        # What FILT3R is working toward
    "milestones",   # Achievements, ISK thresholds crossed, ships unlocked
    "mistakes",     # Bad decisions, losses, things to not repeat
    "market_notes", # Patterns, opportunities, standing observations
    "skill_plan",   # Skill progression goals and targets
    "isk_log",      # ISK snapshots over time
    "session_notes",# Anything Vael wants to remember from last session
}


def _load() -> dict:
    """Load the full memory store."""
    if MEMORY_PATH.exists():
        try:
            return json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning("Memory load failed: %s", e)
            return {}
    return {}


def _save(data: dict) -> None:
    """Persist the full memory store."""
    ensure_dirs()
    MEMORY_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def read_pilot_memory(category: Optional[str] = None) -> dict:
    """
    Read FILT3R's persistent pilot memory.

    If category is specified, returns only that section.
    If category is None, returns the full memory store.

    Categories: goals, milestones, mistakes, market_notes,
                skill_plan, isk_log, session_notes
    """
    data = _load()
    if category:
        if category not in VALID_CATEGORIES:
            return {"error": f"Unknown category '{category}'. Valid: {sorted(VALID_CATEGORIES)}"}
        return {category: data.get(category, {})}
    return data if data else {"note": "No memory stored yet. This is FILT3R's first session."}


def write_pilot_memory(category: str, key: str, value: Any) -> dict:
    """
    Write or update a specific memory entry.

    Examples:
        write_pilot_memory("goals", "primary_goal", "Reach 10M SP and buy a Drake")
        write_pilot_memory("mistakes", "2024-05-07", "Sold Tritanium at Amarr prices when Jita was 15% higher")
        write_pilot_memory("market_notes", "tritanium_trend", "Falling since May 1, watch for floor around 3.5")
        write_pilot_memory("skill_plan", "next_milestone", "Caldari Destroyer V → Drake → PvE missions")
    """
    if category not in VALID_CATEGORIES:
        return {"error": f"Unknown category '{category}'. Valid: {sorted(VALID_CATEGORIES)}"}

    data = _load()
    if category not in data:
        data[category] = {}

    data[category][key] = {
        "value": value,
        "updated": _now(),
    }
    _save(data)
    log.info("Memory written: [%s][%s] = %s", category, key, str(value)[:80])
    return {"status": "saved", "category": category, "key": key, "value": value}


def append_pilot_memory(category: str, entry: str) -> dict:
    """
    Append a timestamped entry to a memory category (for logs and running notes).

    Best for: isk_log entries, mistakes log, session notes.
    Creates a list under category['log'] if it doesn't exist.

    Examples:
        append_pilot_memory("mistakes", "Forgot to check Uedama danger before routing through it")
        append_pilot_memory("milestones", "Hit 100M ISK wallet for the first time")
        append_pilot_memory("session_notes", "Discussed moving to null-sec when skills allow")
    """
    if category not in VALID_CATEGORIES:
        return {"error": f"Unknown category '{category}'."}

    data = _load()
    if category not in data:
        data[category] = {}
    if "log" not in data[category]:
        data[category]["log"] = []

    record = {"time": _now(), "entry": entry}
    data[category]["log"].append(record)

    # Keep logs bounded
    if len(data[category]["log"]) > 200:
        data[category]["log"] = data[category]["log"][-200:]

    _save(data)
    log.info("Memory appended: [%s] %s", category, entry[:80])
    return {"status": "appended", "category": category, "entry": entry}


def log_isk_snapshot(isk_balance: float, note: str = "") -> dict:
    """
    Record an ISK balance snapshot to track growth over time.
    Called automatically during SITREP when wallet is checked.
    """
    data = _load()
    if "isk_log" not in data:
        data["isk_log"] = {}
    if "snapshots" not in data["isk_log"]:
        data["isk_log"]["snapshots"] = []

    snapshot = {
        "time": _now(),
        "isk": isk_balance,
        "note": note,
    }
    data["isk_log"]["snapshots"].append(snapshot)

    # Keep last 500 snapshots
    if len(data["isk_log"]["snapshots"]) > 500:
        data["isk_log"]["snapshots"] = data["isk_log"]["snapshots"][-500:]

    _save(data)
    return {"status": "logged", "isk": isk_balance, "time": snapshot["time"]}


def get_isk_history(last_n: int = 20) -> dict:
    """
    Return the last N ISK snapshots to show wallet growth trend.
    Useful for Vael to comment on ISK velocity and growth rate.
    """
    data = _load()
    snapshots = data.get("isk_log", {}).get("snapshots", [])
    recent = snapshots[-last_n:]

    if len(recent) < 2:
        return {
            "snapshots": recent,
            "note": "Not enough history yet for trend analysis.",
        }

    first = recent[0]["isk"]
    last = recent[-1]["isk"]
    change = last - first
    change_pct = (change / first * 100) if first > 0 else 0

    return {
        "snapshots": recent,
        "oldest_in_window": recent[0]["time"],
        "newest_in_window": recent[-1]["time"],
        "isk_change": change,
        "isk_change_pct": round(change_pct, 2),
        "trend": "growing" if change > 0 else "shrinking" if change < 0 else "flat",
        "formatted_change": (
            f"+{change:,.0f} ISK ({change_pct:+.1f}%)"
            if change >= 0
            else f"{change:,.0f} ISK ({change_pct:+.1f}%)"
        ),
    }


if __name__ == "__main__":
    # Quick self-test
    print("Testing pilot memory...")
    r = write_pilot_memory("goals", "primary", "Reach 10M SP and get into a Drake")
    print("Write:", r)
    r = append_pilot_memory("milestones", "Passed 100M ISK wallet")
    print("Append:", r)
    r = log_isk_snapshot(247_562_923.35, "First session snapshot")
    print("ISK log:", r)
    r = read_pilot_memory()
    print("Full memory keys:", list(r.keys()))
