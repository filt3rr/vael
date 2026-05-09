"""
Event engine — configurable smart watches with compound triggers.

Vael monitors conditions you configure and fires alerts when they're met.
Watches are persistent (stored in pilot_memory) and checked every poll cycle.

Watch types:
    price_below     - alert when item sell price drops below threshold
    price_above     - alert when item buy price rises above threshold
    price_change    - alert when price moves more than N% in 24h
    danger_spike    - alert when system danger rating exceeds threshold
    isk_below       - alert when wallet drops below threshold
    isk_above       - alert when wallet exceeds milestone
    skill_soon      - alert N hours before skill completes
    route_danger    - alert if any system on a route exceeds danger threshold

Usage:
    from eve_agent.event_engine import add_watch, remove_watch, list_watches, check_all_watches
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from eve_agent.config import DATA_DIR, ensure_dirs
from eve_agent.discord_alerts import alert_rich


log = logging.getLogger(__name__)
WATCHES_PATH = DATA_DIR / "watches.json"

VALID_WATCH_TYPES = {
    "price_below", "price_above", "price_change",
    "danger_spike", "isk_below", "isk_above",
    "skill_soon", "route_danger",
}


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
def _load_watches() -> list[dict]:
    if WATCHES_PATH.exists():
        try:
            return json.loads(WATCHES_PATH.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def _save_watches(watches: list[dict]) -> None:
    ensure_dirs()
    WATCHES_PATH.write_text(json.dumps(watches, indent=2), encoding="utf-8")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


# ---------------------------------------------------------------------------
# Watch management
# ---------------------------------------------------------------------------
def add_watch(
    watch_type: str,
    label: str,
    params: dict,
) -> dict:
    """
    Add a new watch condition.

    Examples:
        add_watch("price_below", "Tritanium cheap",
                  {"item": "Tritanium", "threshold": 3.50, "hub": "Jita"})

        add_watch("danger_spike", "Uedama flaring",
                  {"system": "Uedama", "threshold": 8})

        add_watch("isk_above", "Hit 500M milestone",
                  {"threshold": 500_000_000})

        add_watch("skill_soon", "Nav V finishing",
                  {"hours_before": 2})
    """
    if watch_type not in VALID_WATCH_TYPES:
        return {"error": f"Unknown watch type '{watch_type}'. Valid: {sorted(VALID_WATCH_TYPES)}"}

    watches = _load_watches()

    # Check for duplicate label
    if any(w["label"] == label for w in watches):
        return {"error": f"Watch '{label}' already exists. Remove it first or use a different label."}

    watch = {
        "id": int(time.time() * 1000),
        "type": watch_type,
        "label": label,
        "params": params,
        "created": _now(),
        "last_triggered": None,
        "trigger_count": 0,
        "active": True,
    }
    watches.append(watch)
    _save_watches(watches)
    log.info("Watch added: [%s] %s", watch_type, label)
    return {"status": "added", "watch": watch}


def remove_watch(label: str) -> dict:
    """Remove a watch by its label."""
    watches = _load_watches()
    before = len(watches)
    watches = [w for w in watches if w["label"] != label]
    if len(watches) == before:
        return {"error": f"No watch found with label '{label}'."}
    _save_watches(watches)
    return {"status": "removed", "label": label}


def list_watches() -> dict:
    """List all configured watches."""
    watches = _load_watches()
    return {
        "count": len(watches),
        "watches": watches,
    }


def clear_all_watches() -> dict:
    """Remove all watches."""
    _save_watches([])
    return {"status": "cleared"}


# ---------------------------------------------------------------------------
# Watch evaluation
# ---------------------------------------------------------------------------
async def _check_price_watch(watch: dict) -> Optional[dict]:
    """Check price_below or price_above watches."""
    from eve_agent.tools.market import get_market_price
    params = watch["params"]
    item = params.get("item", "")
    threshold = params.get("threshold", 0)
    hub = params.get("hub", "Jita")
    watch_type = watch["type"]

    try:
        prices = await get_market_price(item, hub)
        if "error" in prices:
            return None

        if watch_type == "price_below":
            price = prices.get("best_sell")
            if price and price < threshold:
                return {
                    "triggered": True,
                    "message": f"{item} sell price {price:,.2f} ISK is below your threshold of {threshold:,.2f}",
                    "data": {"current": price, "threshold": threshold, "hub": hub},
                }
        elif watch_type == "price_above":
            price = prices.get("best_buy")
            if price and price > threshold:
                return {
                    "triggered": True,
                    "message": f"{item} buy price {price:,.2f} ISK exceeded your threshold of {threshold:,.2f}",
                    "data": {"current": price, "threshold": threshold, "hub": hub},
                }
    except Exception as e:
        log.warning("Price watch check failed for %s: %s", item, e)
    return None


async def _check_danger_watch(watch: dict) -> Optional[dict]:
    """Check danger_spike watches."""
    from eve_agent.tools.intel import get_system_danger
    params = watch["params"]
    system = params.get("system", "")
    threshold = params.get("threshold", 7)

    try:
        danger = await get_system_danger(system)
        rating = danger.get("danger_rating", 0)
        if rating >= threshold:
            return {
                "triggered": True,
                "message": f"{system} danger is {rating}/10 — above your threshold of {threshold}. {danger.get('kills_last_7d', 0)} kills this week.",
                "data": {"system": system, "rating": rating, "threshold": threshold},
            }
    except Exception as e:
        log.warning("Danger watch check failed for %s: %s", system, e)
    return None


async def _check_isk_watch(watch: dict) -> Optional[dict]:
    """Check isk_below or isk_above watches."""
    from eve_agent.tools.character import get_wallet_balance
    params = watch["params"]
    threshold = params.get("threshold", 0)
    watch_type = watch["type"]

    try:
        wallet = await get_wallet_balance()
        balance = wallet.get("isk_balance", 0)

        if watch_type == "isk_below" and balance < threshold:
            return {
                "triggered": True,
                "message": f"Wallet dropped to {balance:,.0f} ISK — below your threshold of {threshold:,.0f}",
                "data": {"current": balance, "threshold": threshold},
            }
        elif watch_type == "isk_above" and balance > threshold:
            return {
                "triggered": True,
                "message": f"Wallet hit {balance:,.0f} ISK — milestone of {threshold:,.0f} reached!",
                "data": {"current": balance, "threshold": threshold},
            }
    except Exception as e:
        log.warning("ISK watch check failed: %s", e)
    return None


async def _check_skill_soon_watch(watch: dict) -> Optional[dict]:
    """Check skill_soon watches — fires N hours before queue ends."""
    from eve_agent.tools.skills import get_skill_queue
    params = watch["params"]
    hours_before = params.get("hours_before", 2)

    try:
        queue = await get_skill_queue()
        queue_days = queue.get("queue_total_days")
        if queue_days is not None and queue_days * 24 <= hours_before:
            entries = queue.get("queue", [])
            finishing = entries[0] if entries else {}
            return {
                "triggered": True,
                "message": f"Skill queue ends in {queue_days * 24:.1f} hours. Queue next skill now.",
                "data": {
                    "hours_remaining": queue_days * 24,
                    "finishing_skill": finishing.get("skill"),
                    "finishing_level": finishing.get("to_level"),
                },
            }
    except Exception as e:
        log.warning("Skill watch check failed: %s", e)
    return None


async def _check_route_danger_watch(watch: dict) -> Optional[dict]:
    """Check route_danger watches — evaluate all systems on a route."""
    from eve_agent.tools.intel import get_system_danger
    params = watch["params"]
    systems = params.get("systems", [])
    threshold = params.get("threshold", 6)

    hot_systems = []
    for system in systems:
        try:
            danger = await get_system_danger(system)
            rating = danger.get("danger_rating", 0)
            if rating >= threshold:
                hot_systems.append({"system": system, "rating": rating})
        except Exception:
            pass

    if hot_systems:
        names = ", ".join(f"{s['system']} ({s['rating']}/10)" for s in hot_systems)
        return {
            "triggered": True,
            "message": f"Route alert: {len(hot_systems)} dangerous system(s) — {names}",
            "data": {"hot_systems": hot_systems, "threshold": threshold},
        }
    return None


# Watch type dispatch
WATCH_CHECKERS = {
    "price_below": _check_price_watch,
    "price_above": _check_price_watch,
    "danger_spike": _check_danger_watch,
    "isk_below": _check_isk_watch,
    "isk_above": _check_isk_watch,
    "skill_soon": _check_skill_soon_watch,
    "route_danger": _check_route_danger_watch,
}

# Cooldowns per watch type (seconds) — prevents spam
WATCH_COOLDOWNS = {
    "price_below":  3600,    # 1 hour
    "price_above":  3600,
    "price_change": 7200,
    "danger_spike": 1800,    # 30 min
    "isk_below":    3600,
    "isk_above":    86400,   # 24h — milestones shouldn't fire twice
    "skill_soon":   3600,
    "route_danger": 1800,
}


async def check_all_watches(
    send_discord: bool = True,
    send_toast: bool = True,
) -> dict:
    """
    Evaluate all active watches and fire alerts for any that trigger.
    Called by the notifier on each poll cycle.
    """
    watches = _load_watches()
    if not watches:
        return {"watches_checked": 0, "triggered": 0}

    triggered_count = 0
    results = []
    now = time.time()

    for watch in watches:
        if not watch.get("active", True):
            continue

        watch_type = watch["type"]
        checker = WATCH_CHECKERS.get(watch_type)
        if not checker:
            continue

        # Cooldown check
        last_triggered = watch.get("last_triggered_ts", 0) or 0
        cooldown = WATCH_COOLDOWNS.get(watch_type, 3600)
        if now - last_triggered < cooldown:
            continue

        try:
            result = await checker(watch)
        except Exception as e:
            log.warning("Watch check error [%s]: %s", watch["label"], e)
            result = None

        if result and result.get("triggered"):
            triggered_count += 1
            label = watch["label"]
            message = result["message"]

            log.info("Watch triggered: [%s] %s", label, message)

            # Update trigger metadata
            watch["last_triggered"] = _now()
            watch["last_triggered_ts"] = now
            watch["trigger_count"] = watch.get("trigger_count", 0) + 1

            # Discord
            if send_discord:
                color_map = {
                    "price_below": "market", "price_above": "market",
                    "danger_spike": "danger", "isk_below": "warning",
                    "isk_above": "success", "skill_soon": "skill",
                    "route_danger": "danger",
                }
                alert_rich(
                    title=f"Watch: {label}",
                    description=message,
                    color=color_map.get(watch_type, "neutral"),
                    fields=result.get("data", {}),
                    footer="Vael Watch System",
                )

            # Toast
            if send_toast:
                try:
                    from win10toast_click import ToastNotifier
                    ToastNotifier().show_toast(
                        f"Vael | {label}", message[:120], duration=8, threaded=True
                    )
                except Exception:
                    print(f"\n>>> Watch: {label}\n    {message}\n")

            results.append({"label": label, "message": message})

    _save_watches(watches)
    return {
        "watches_checked": len(watches),
        "triggered": triggered_count,
        "results": results,
    }


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    print(json.dumps(list_watches(), indent=2))
