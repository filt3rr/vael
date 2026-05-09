"""
Intel tools — PvP danger assessment, killboard lookups, system activity.

Uses the zKillboard public API (no auth required) plus ESI public endpoints.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import httpx

from eve_agent import auth
from eve_agent.esi_client import ESIClient
from eve_agent.sde import get_system, get_type, search_systems
from eve_agent.config import settings


log = logging.getLogger(__name__)

ZKILL_BASE = "https://zkillboard.com/api"
ZKILL_HEADERS = {
    "User-Agent": settings.eve_user_agent,
    "Accept": "application/json",
}


def _zkill_get(path: str, timeout: int = 15) -> list | dict:
    url = f"{ZKILL_BASE}{path}"
    try:
        resp = httpx.get(url, headers=ZKILL_HEADERS, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        log.warning("zKillboard request failed: %s — %s", url, e)
        return []


def _resolve_system(name_or_id: str) -> Optional[dict]:
    s = str(name_or_id).strip()
    if s.isdigit():
        return get_system(int(s))
    matches = search_systems(s, limit=3)
    if not matches:
        return None
    for m in matches:
        if m["name"].lower() == s.lower():
            return get_system(m["system_id"])
    return get_system(matches[0]["system_id"])


def _format_isk(value: float) -> str:
    if value >= 1_000_000_000:
        return f"{value/1_000_000_000:.2f}B ISK"
    if value >= 1_000_000:
        return f"{value/1_000_000:.1f}M ISK"
    return f"{value:,.0f} ISK"


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
async def get_system_danger(system: str) -> dict:
    """
    Assess the danger level of a solar system based on recent kill activity.
    Returns kill count (last 7 days), most common ship types killed,
    danger rating (1-10), and a recommendation.
    """
    sys_info = _resolve_system(system)
    if not sys_info:
        return {"error": f"Could not resolve system '{system}'."}

    system_id = sys_info["system_id"]
    kills = _zkill_get(f"/solarSystemID/{system_id}/pastSeconds/604800/")

    if not kills:
        return {
            "system": sys_info["name"],
            "security": sys_info["security"],
            "region": sys_info.get("region_name"),
            "kills_last_7d": 0,
            "danger_rating": 1,
            "recommendation": "Very quiet. No kills in the last 7 days.",
        }

    total_value = sum(k.get("zkb", {}).get("totalValue", 0) for k in kills)
    ship_kills: dict[int, int] = {}
    for k in kills:
        tid = k.get("victim", {}).get("ship_type_id")
        if tid:
            ship_kills[tid] = ship_kills.get(tid, 0) + 1

    top_ships = []
    for type_id, count in sorted(ship_kills.items(), key=lambda x: -x[1])[:5]:
        t = get_type(type_id)
        top_ships.append({"ship": t["name"] if t else f"Type {type_id}", "kills": count})

    sec = sys_info["security"]
    base = 2 if sec >= 0.5 else (5 if sec >= 0.1 else 7)
    kill_factor = min(5, len(kills) // 3)
    danger = min(10, base + kill_factor)

    recs = {
        (1, 2): "Very safe. Minimal PvP activity.",
        (3, 4): "Relatively calm. Stay aligned and use d-scan.",
        (5, 6): "Moderate danger. Avoid AFK travel. Watch local.",
        (7, 8): "High danger. Fly cheap or prepared. Watch local for reds.",
        (9, 10): "Extremely dangerous. Do not enter without a fleet.",
    }
    rec = next(v for (lo, hi), v in recs.items() if lo <= danger <= hi)

    return {
        "system": sys_info["name"],
        "system_id": system_id,
        "security": round(sec, 2),
        "security_class": "highsec" if sec >= 0.5 else "lowsec" if sec >= 0.0 else "nullsec",
        "region": sys_info.get("region_name"),
        "kills_last_7d": len(kills),
        "total_isk_destroyed": _format_isk(total_value),
        "most_killed_ships": top_ships,
        "danger_rating": danger,
        "danger_scale": f"{danger}/10",
        "recommendation": rec,
    }


async def get_character_intel(character_name: str) -> dict:
    """
    Pull public intel on a character: corp, alliance, security status,
    killboard stats, recent kills and losses.
    """
    # Use /universe/ids/ (public endpoint, no auth needed)
    async with ESIClient() as esi:
        try:
            result = await esi.raw_request(
                "POST",
                "/universe/ids/",
                authenticated=False,
                use_cache=False,
            )
            # POST not supported via our client — use httpx directly
        except Exception:
            pass

        # Direct POST via httpx since our ESI client only wraps GET
        try:
            resp = httpx.post(
                "https://esi.evetech.net/latest/universe/ids/",
                json=[character_name],
                headers={
                    "User-Agent": settings.eve_user_agent,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            return {"error": f"ESI universe/ids lookup failed: {e}"}

    characters = data.get("characters", [])
    if not characters:
        return {"error": f"No character found matching '{character_name}'."}

    char_id = characters[0]["id"]
    char_name_resolved = characters[0]["name"]

    async with ESIClient() as esi:
        char_info = await esi.get(f"/characters/{char_id}/", authenticated=False)
        corp = await esi.get(
            f"/corporations/{char_info['corporation_id']}/", authenticated=False
        )
        alliance_name = None
        if "alliance_id" in char_info:
            alliance = await esi.get(
                f"/alliances/{char_info['alliance_id']}/", authenticated=False
            )
            alliance_name = alliance.get("name")

    # zKillboard stats
    zkill_stats = _zkill_get(f"/characterID/{char_id}/stats/")
    if isinstance(zkill_stats, list) and zkill_stats:
        zkill_stats = zkill_stats[0]

    # Recent kills and losses
    recent_kills_raw = _zkill_get(f"/characterID/{char_id}/kills/page/1/")
    recent_losses_raw = _zkill_get(f"/characterID/{char_id}/losses/page/1/")

    recent_kills = []
    for k in recent_kills_raw[:5]:
        victim = k.get("victim", {})
        t = get_type(victim.get("ship_type_id", 0))
        recent_kills.append({
            "ship_killed": t["name"] if t else "Unknown",
            "value": _format_isk(k.get("zkb", {}).get("totalValue", 0)),
        })

    recent_losses = []
    for k in recent_losses_raw[:5]:
        victim = k.get("victim", {})
        t = get_type(victim.get("ship_type_id", 0))
        recent_losses.append({
            "ship_lost": t["name"] if t else "Unknown",
            "value": _format_isk(k.get("zkb", {}).get("totalValue", 0)),
        })

    age_days = None
    if char_info.get("birthday"):
        try:
            bd = datetime.fromisoformat(char_info["birthday"].replace("Z", "+00:00"))
            age_days = (datetime.now(timezone.utc) - bd).days
        except Exception:
            pass

    zkill = {}
    if isinstance(zkill_stats, dict):
        ats = zkill_stats.get("allTimeSum", {})
        zkill = {
            "kills": ats.get("kills"),
            "losses": ats.get("losses"),
            "isk_destroyed": _format_isk(ats.get("iskDestroyed", 0)),
            "isk_lost": _format_isk(ats.get("iskLost", 0)),
        }

    return {
        "character_id": char_id,
        "character_name": char_name_resolved,
        "age_days": age_days,
        "security_status": round(char_info.get("security_status", 0), 3),
        "corporation": corp.get("name"),
        "corporation_ticker": corp.get("ticker"),
        "corporation_member_count": corp.get("member_count"),
        "alliance": alliance_name,
        "zkillboard": zkill,
        "recent_kills": recent_kills,
        "recent_losses": recent_losses,
        "profile_url": f"https://zkillboard.com/character/{char_id}/",
    }


async def get_recent_kills_in_system(system: str, limit: int = 10) -> dict:
    """Recent kills in a solar system from zKillboard."""
    sys_info = _resolve_system(system)
    if not sys_info:
        return {"error": f"Could not resolve system '{system}'."}

    system_id = sys_info["system_id"]
    kills = _zkill_get(f"/solarSystemID/{system_id}/page/1/")

    enriched = []
    for k in kills[:limit]:
        victim = k.get("victim", {})
        ship = get_type(victim.get("ship_type_id", 0))
        enriched.append({
            "killmail_id": k.get("killmail_id"),
            "ship_lost": ship["name"] if ship else "Unknown",
            "value": _format_isk(k.get("zkb", {}).get("totalValue", 0)),
            "time": k.get("killmail_time", ""),
            "attackers": len(k.get("attackers", [])),
            "solo_kill": k.get("zkb", {}).get("solo", False),
        })

    return {
        "system": sys_info["name"],
        "security": round(sys_info["security"], 2),
        "region": sys_info.get("region_name"),
        "recent_kills": enriched,
        "count": len(enriched),
    }


async def should_i_undock(ship_value_isk: float = 0) -> dict:
    """
    Safety assessment for undocking in your current location.
    Checks local system danger and compares against ship value.
    """
    from eve_agent.tools.character import get_current_location
    loc = await get_current_location()
    if "error" in loc:
        return {"error": "Could not determine current location."}

    system_name = loc.get("system_name", "")
    danger = await get_system_danger(system_name)

    assessment = {
        "current_system": system_name,
        "security_class": danger.get("security_class"),
        "danger_rating": danger.get("danger_rating"),
        "kills_last_7d": danger.get("kills_last_7d"),
        "recommendation": danger.get("recommendation"),
    }

    if ship_value_isk > 0:
        dr = danger.get("danger_rating", 0)
        if dr >= 7 and ship_value_isk >= 100_000_000:
            assessment["ship_risk"] = f"WARNING: {_format_isk(ship_value_isk)} at risk in a {dr}/10 danger zone."
        elif dr >= 5 and ship_value_isk >= 500_000_000:
            assessment["ship_risk"] = f"CAUTION: {_format_isk(ship_value_isk)} is significant value for this system."
        else:
            assessment["ship_risk"] = f"{_format_isk(ship_value_isk)} in a {dr}/10 danger system — acceptable risk."

    return assessment


async def get_regional_kill_activity(region: str = "The Forge", top_n: int = 5) -> dict:
    """Kill activity in a region: hottest systems and most-killed ships."""
    from eve_agent.sde import _conn
    row = _conn().execute(
        "SELECT regionID, regionName FROM mapRegions WHERE regionName LIKE ? COLLATE NOCASE LIMIT 1",
        (f"%{region}%",),
    ).fetchone()
    if not row:
        return {"error": f"Could not resolve region '{region}'."}

    region_id, region_name = row[0], row[1]
    kills = _zkill_get(f"/regionID/{region_id}/pastSeconds/604800/")

    if not kills:
        return {"region": region_name, "kills_last_7d": 0, "message": "No kill data available."}

    system_counts: dict[int, int] = {}
    ship_counts: dict[int, int] = {}
    total_value = 0.0

    for k in kills:
        sid = k.get("solar_system_id")
        if sid:
            system_counts[sid] = system_counts.get(sid, 0) + 1
        tid = k.get("victim", {}).get("ship_type_id")
        if tid:
            ship_counts[tid] = ship_counts.get(tid, 0) + 1
        total_value += k.get("zkb", {}).get("totalValue", 0)

    hot_systems = []
    for sid, count in sorted(system_counts.items(), key=lambda x: -x[1])[:top_n]:
        si = get_system(sid)
        hot_systems.append({
            "system": si["name"] if si else f"System {sid}",
            "kills": count,
            "security": round(si["security"], 2) if si else None,
        })

    popular_targets = []
    for tid, count in sorted(ship_counts.items(), key=lambda x: -x[1])[:top_n]:
        t = get_type(tid)
        popular_targets.append({"ship": t["name"] if t else f"Type {tid}", "times_killed": count})

    return {
        "region": region_name,
        "kills_last_7d": len(kills),
        "total_isk_destroyed": _format_isk(total_value),
        "most_dangerous_systems": hot_systems,
        "most_killed_ships": popular_targets,
    }