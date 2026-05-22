"""
EVE Agent MCP server — Phase III + Exploration tools.
44 tools. Run as: python -m eve_agent.server
"""

from __future__ import annotations
import logging
import sys
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP
from eve_agent.config import LOGS_DIR, ensure_dirs

ensure_dirs()
log_path = LOGS_DIR / "server.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.FileHandler(log_path, encoding="utf-8")],
)
log = logging.getLogger("eve_agent.server")

from eve_agent.tools import character as char
from eve_agent.tools import market as mkt
from eve_agent.tools import industry as ind
from eve_agent.tools import skills as sk
from eve_agent.tools import intel as itl
from eve_agent import pilot_memory as mem
from eve_agent import pnl_engine as pnl
from eve_agent import event_engine as events
from eve_agent import fittings as fit_module
from eve_agent import exploration_guide as exp

mcp = FastMCP("eve-agent")


# ===========================================================================
# PILOT MEMORY
# ===========================================================================
@mcp.tool()
async def read_pilot_memory(category: Optional[str] = None) -> dict[str, Any]:
    """Read the capsuleer's persistent cross-session memory. Call at every session start."""
    log.info("tool: read_pilot_memory(category=%s)", category)
    return mem.read_pilot_memory(category)

@mcp.tool()
async def write_pilot_memory(category: str, key: str, value: str) -> dict[str, Any]:
    """Persist a memory entry. Categories: goals, milestones, mistakes, market_notes, skill_plan, session_notes."""
    log.info("tool: write_pilot_memory(%s, %s)", category, key)
    return mem.write_pilot_memory(category, key, value)

@mcp.tool()
async def append_pilot_memory(category: str, entry: str) -> dict[str, Any]:
    """Append a timestamped log entry. Best for mistakes, milestones, session_notes."""
    log.info("tool: append_pilot_memory(%s)", category)
    return mem.append_pilot_memory(category, entry)

@mcp.tool()
async def log_isk_snapshot(note: str = "") -> dict[str, Any]:
    """Record current ISK balance as a timestamped snapshot. Call during SITREP."""
    log.info("tool: log_isk_snapshot")
    wallet = await char.get_wallet_balance()
    isk = wallet.get("isk_balance", 0)
    return mem.log_isk_snapshot(isk, note)

@mcp.tool()
async def get_isk_history(last_n: int = 20) -> dict[str, Any]:
    """ISK wallet snapshots over time showing growth rate and trend."""
    log.info("tool: get_isk_history(last_n=%d)", last_n)
    return mem.get_isk_history(last_n)


# ===========================================================================
# CHARACTER
# ===========================================================================
@mcp.tool()
async def get_character_summary() -> dict[str, Any]:
    """Full snapshot: name, corp, ISK, location, ship, online status."""
    log.info("tool: get_character_summary")
    return await char.get_character_summary()

@mcp.tool()
async def get_wallet_balance() -> dict[str, Any]:
    """Current ISK wallet balance."""
    log.info("tool: get_wallet_balance")
    return await char.get_wallet_balance()

@mcp.tool()
async def get_skill_overview() -> dict[str, Any]:
    """Total SP, unallocated SP, queue length, currently training."""
    log.info("tool: get_skill_overview")
    return await char.get_skill_overview()

@mcp.tool()
async def get_current_location() -> dict[str, Any]:
    """Current system, security, region, docked status, ship."""
    log.info("tool: get_current_location")
    return await char.get_current_location()

@mcp.tool()
async def get_asset_summary(top_n: int = 10) -> dict[str, Any]:
    """Assets by quantity and category."""
    log.info("tool: get_asset_summary(top_n=%d)", top_n)
    return await char.get_asset_summary(top_n=top_n)

@mcp.tool()
async def get_assets_by_location(top_n: int = 10) -> dict[str, Any]:
    """Map of where the capsuleer's stuff is: top locations bucketed by station/system with item counts, ship counts, and category mix. Use when asked where things are stashed or to identify home systems."""
    log.info("tool: get_assets_by_location(top_n=%d)", top_n)
    return await char.get_assets_by_location(top_n=top_n)

@mcp.tool()
async def list_assets_at_location(location_id: int, category: str = "") -> dict[str, Any]:
    """List every item at a specific location (station/system) with name, qty, and category. Optional category filter (e.g. 'Ship', 'Planetary Commodities'). Use after get_assets_by_location to drill into a hub."""
    log.info("tool: list_assets_at_location(location_id=%d, category=%r)", location_id, category)
    return await char.list_assets_at_location(location_id=location_id, category=category or None)

@mcp.tool()
async def list_recent_wallet_journal(limit: int = 20) -> dict[str, Any]:
    """Recent wallet journal entries."""
    log.info("tool: list_recent_wallet_journal(limit=%d)", limit)
    return await char.list_recent_wallet_journal(limit=limit)


# ===========================================================================
# FITTINGS & SHIP EQUIPMENT
# ===========================================================================
@mcp.tool()
async def get_saved_fittings() -> dict[str, Any]:
    """
    Read ship fittings saved in-game via the fitting window (Alt+F -> Save Fitting).
    Returns named loadouts with full module slot detail.
    Use this to see what fits the capsuleer has saved.
    """
    log.info("tool: get_saved_fittings")
    return await fit_module.get_saved_fittings()

@mcp.tool()
async def get_active_ship_equipment() -> dict[str, Any]:
    """
    Read what modules are currently fitted to the active ship by checking
    asset location flags. Returns modules grouped by slot type (high/mid/low/rigs).
    Use this when asked 'what do I have fitted?' or 'check my fit'.
    """
    log.info("tool: get_active_ship_equipment")
    return await fit_module.get_active_ship_equipment()

@mcp.tool()
async def recommend_exploration_fit(budget_isk: float = 50_000_000) -> dict[str, Any]:
    """
    Recommend an optimal Heron exploration fit for the capsuleer's current skill level.
    Returns module list with roles explained, skill notes, and cost estimate.
    Use this when asked about how to fit the Heron or what to buy for exploration.
    """
    log.info("tool: recommend_exploration_fit(budget=%.0f)", budget_isk)
    return await fit_module.recommend_exploration_fit(budget_isk)


# ===========================================================================
# EXPLORATION KNOWLEDGE
# ===========================================================================
@mcp.tool()
async def get_scanning_walkthrough() -> dict[str, Any]:
    """
    Step-by-step guide to core probe scanning in EVE.
    Walk the capsuleer through launching probes, scanning signatures, focusing on hits,
    and warping to sites. Use when asked how to scan or use probes.
    """
    log.info("tool: get_scanning_walkthrough")
    return exp.get_scanning_walkthrough()

@mcp.tool()
async def get_site_type_guide() -> dict[str, Any]:
    """
    Reference for all cosmic signature types: Relic, Data, Combat, Gas, Wormhole.
    Includes ISK potential, required analyzer, and which to prioritize.
    Use when asked what sites to run or what to look for while exploring.
    """
    log.info("tool: get_site_type_guide")
    return exp.get_site_type_guide()

@mcp.tool()
async def get_hacking_guide() -> dict[str, Any]:
    """
    Complete guide to the hacking minigame: node types, utility subsystems,
    strategy, and common mistakes. Use when asked how to hack or what nodes mean.
    """
    log.info("tool: get_hacking_guide")
    return exp.get_hacking_guide()

@mcp.tool()
async def get_exploration_isk_guide() -> dict[str, Any]:
    """
    Realistic ISK expectations for exploration by security class.
    Highsec vs lowsec hourly rates, what affects earnings, when to graduate
    from highsec to lowsec. Use when asked how much exploration pays.
    """
    log.info("tool: get_exploration_isk_guide")
    return exp.get_isk_expectations()

@mcp.tool()
async def get_full_exploration_primer() -> dict[str, Any]:
    """
    The complete exploration package: scanning guide, site types, hacking guide,
    ISK expectations, and quick reference card. Use at the start of an exploration
    session or when the capsuleer asks for a comprehensive exploration guide.
    """
    log.info("tool: get_full_exploration_primer")
    return exp.get_full_exploration_primer()


# ===========================================================================
# SDE LOOKUPS
# ===========================================================================
@mcp.tool()
async def lookup_item(name_or_id: str) -> dict[str, Any]:
    """Look up any EVE item, ship, or module by name or type ID."""
    log.info("tool: lookup_item(%s)", name_or_id)
    from eve_agent.sde import get_type, search_types
    s = name_or_id.strip()
    if s.isdigit():
        t = get_type(int(s))
        return t or {"error": f"No type with id {s}."}
    matches = search_types(s, limit=10)
    if not matches: return {"error": f"No item type matching '{s}'."}
    if len(matches) == 1: return get_type(matches[0]["type_id"])
    return {"matches": matches, "note": f"{len(matches)} matches."}

@mcp.tool()
async def lookup_system(name_or_id: str) -> dict[str, Any]:
    """Look up a solar system by name or system ID."""
    log.info("tool: lookup_system(%s)", name_or_id)
    from eve_agent.sde import get_system, search_systems
    s = name_or_id.strip()
    if s.isdigit(): return get_system(int(s)) or {"error": f"No system with id {s}."}
    matches = search_systems(s, limit=10)
    if not matches: return {"error": f"No system matching '{s}'."}
    if len(matches) == 1: return get_system(matches[0]["system_id"])
    return {"matches": matches}

@mcp.tool()
async def jumps_between(from_system: str, to_system: str) -> dict[str, Any]:
    """Shortest gate-jump count between two solar systems."""
    log.info("tool: jumps_between(%s -> %s)", from_system, to_system)
    from eve_agent.sde import distance_between, search_systems, get_system
    def resolve(s):
        s = s.strip()
        if s.isdigit(): return get_system(int(s))
        m = search_systems(s, limit=2)
        if len(m) == 1: return get_system(m[0]["system_id"])
        for x in m:
            if x["name"].lower() == s.lower(): return get_system(x["system_id"])
        return None
    a, b = resolve(from_system), resolve(to_system)
    if not a: return {"error": f"Could not resolve '{from_system}'."}
    if not b: return {"error": f"Could not resolve '{to_system}'."}
    d = distance_between(a["system_id"], b["system_id"])
    return {"from": a["name"], "to": b["name"], "jumps": d, "reachable": d is not None}


# ===========================================================================
# MARKET
# ===========================================================================
@mcp.tool()
async def get_market_price(item: str, hub: str = "Jita") -> dict[str, Any]:
    """Live best buy/sell in a hub (Jita/Amarr/Dodixie/Rens/Hek)."""
    log.info("tool: get_market_price(%s, %s)", item, hub)
    return await mkt.get_market_price(item, hub)

@mcp.tool()
async def compare_hub_prices(item: str) -> dict[str, Any]:
    """Compare prices across all major hubs. Finds arbitrage."""
    log.info("tool: compare_hub_prices(%s)", item)
    return await mkt.compare_hub_prices(item)

@mcp.tool()
async def get_market_history(item: str, region: str = "Jita", days: int = 30) -> dict[str, Any]:
    """Daily price history: avg, volume, high/low, 7-day trend."""
    log.info("tool: get_market_history(%s, days=%d)", item, days)
    return await mkt.get_market_history(item, region, days)

@mcp.tool()
async def get_my_market_orders() -> dict[str, Any]:
    """All open buy and sell orders."""
    log.info("tool: get_my_market_orders")
    return await mkt.get_my_market_orders()


# ===========================================================================
# INDUSTRY
# ===========================================================================
@mcp.tool()
async def get_active_industry_jobs() -> dict[str, Any]:
    """Active industry jobs."""
    log.info("tool: get_active_industry_jobs")
    return await ind.get_active_industry_jobs()

@mcp.tool()
async def get_blueprint_info(item: str) -> dict[str, Any]:
    """Bill of materials and manufacturing time."""
    log.info("tool: get_blueprint_info(%s)", item)
    return await ind.get_blueprint_info(item)

@mcp.tool()
async def calculate_manufacturing_cost(item: str, runs: int = 1, me_level: int = 0, hub: str = "Jita") -> dict[str, Any]:
    """Live manufacturing cost, revenue, profit, and margin."""
    log.info("tool: calculate_manufacturing_cost(%s, runs=%d, me=%d)", item, runs, me_level)
    return await ind.calculate_manufacturing_cost(item, runs, me_level, hub)


# ===========================================================================
# SKILLS
# ===========================================================================
@mcp.tool()
async def calculate_training_time(skill: str, target_level: int, sp_per_minute: float = 30.0) -> dict[str, Any]:
    """Training time from current level to target."""
    log.info("tool: calculate_training_time(%s, level=%d)", skill, target_level)
    return await sk.calculate_training_time(skill, target_level, sp_per_minute)

@mcp.tool()
async def can_i_fly(ship: str) -> dict[str, Any]:
    """Check ship prerequisites. Lists missing skills."""
    log.info("tool: can_i_fly(%s)", ship)
    return await sk.can_i_fly(ship)

@mcp.tool()
async def get_skill_queue() -> dict[str, Any]:
    """Full training queue with finish dates."""
    log.info("tool: get_skill_queue")
    return await sk.get_skill_queue()

@mcp.tool()
async def suggest_next_skills(top_n: int = 5) -> dict[str, Any]:
    """High-value foundational skills to train next."""
    log.info("tool: suggest_next_skills(top_n=%d)", top_n)
    return await sk.suggest_next_skills(top_n)


# ===========================================================================
# INTEL
# ===========================================================================
@mcp.tool()
async def get_system_danger(system: str) -> dict[str, Any]:
    """Danger rating 1-10 from zKillboard 7-day kill data."""
    log.info("tool: get_system_danger(%s)", system)
    return await itl.get_system_danger(system)

@mcp.tool()
async def get_character_intel(character_name: str) -> dict[str, Any]:
    """Public dossier: corp, alliance, age, killboard stats."""
    log.info("tool: get_character_intel(%s)", character_name)
    return await itl.get_character_intel(character_name)

@mcp.tool()
async def get_recent_kills_in_system(system: str, limit: int = 10) -> dict[str, Any]:
    """Recent kills in a system from zKillboard."""
    log.info("tool: get_recent_kills_in_system(%s)", system)
    return await itl.get_recent_kills_in_system(system, limit)

@mcp.tool()
async def should_i_undock(ship_value_isk: float = 0) -> dict[str, Any]:
    """Undocking risk assessment for current location."""
    log.info("tool: should_i_undock(%.0f)", ship_value_isk)
    return await itl.should_i_undock(ship_value_isk)

@mcp.tool()
async def get_regional_kill_activity(region: str = "The Forge", top_n: int = 5) -> dict[str, Any]:
    """Regional kill heat map: hottest systems, most-killed ships."""
    log.info("tool: get_regional_kill_activity(%s)", region)
    return await itl.get_regional_kill_activity(region, top_n)


# ===========================================================================
# P&L ENGINE
# ===========================================================================
@mcp.tool()
async def get_pnl_summary(days: int = 7) -> dict[str, Any]:
    """P&L summary: total income, expenses, net profit, breakdown by activity."""
    log.info("tool: get_pnl_summary(days=%d)", days)
    return await pnl.get_pnl_summary(days)

@mcp.tool()
async def get_isk_velocity() -> dict[str, Any]:
    """ISK growth rate: per-hour, per-day, per-week, milestone projections."""
    log.info("tool: get_isk_velocity")
    return await pnl.get_isk_velocity()

@mcp.tool()
async def analyze_trading_performance(days: int = 14) -> dict[str, Any]:
    """Which items are winning vs losing in your trading portfolio."""
    log.info("tool: analyze_trading_performance(days=%d)", days)
    return await pnl.analyze_trading_performance(days)

@mcp.tool()
async def get_activity_breakdown(days: int = 7) -> dict[str, Any]:
    """What is making you ISK — breakdown by activity type."""
    log.info("tool: get_activity_breakdown(days=%d)", days)
    return await pnl.get_activity_breakdown(days)

@mcp.tool()
async def project_isk_growth(target_isk: float, scenario: str = "current") -> dict[str, Any]:
    """Project time to reach a target ISK at current/optimistic/conservative velocity."""
    log.info("tool: project_isk_growth(target=%.0f, scenario=%s)", target_isk, scenario)
    return await pnl.project_isk_growth(target_isk, scenario)


# ===========================================================================
# EVENT WATCHES
# ===========================================================================
@mcp.tool()
async def add_watch(watch_type: str, label: str, params: dict) -> dict[str, Any]:
    """
    Add a proactive watch that fires Discord/toast alerts when triggered.
    Types: price_below, price_above, danger_spike, isk_below, isk_above, skill_soon, route_danger.
    Example: add_watch('price_below', 'Trit cheap', {'item':'Tritanium','threshold':3.50,'hub':'Jita'})
    """
    log.info("tool: add_watch(%s, %s)", watch_type, label)
    return events.add_watch(watch_type, label, params)

@mcp.tool()
async def remove_watch(label: str) -> dict[str, Any]:
    """Remove a watch by its label."""
    log.info("tool: remove_watch(%s)", label)
    return events.remove_watch(label)

@mcp.tool()
async def list_watches() -> dict[str, Any]:
    """List all configured watch conditions."""
    log.info("tool: list_watches")
    return events.list_watches()

@mcp.tool()
async def check_watches_now() -> dict[str, Any]:
    """Immediately evaluate all active watches and fire any that trigger."""
    log.info("tool: check_watches_now")
    return await events.check_all_watches(send_discord=True, send_toast=True)


# ===========================================================================
# WEEKLY DIGEST
# ===========================================================================
@mcp.tool()
async def generate_weekly_digest(post_to_discord: bool = False) -> dict[str, Any]:
    """
    Generate weekly summary: ISK performance, skills, market activity, goals, assessment.
    Saves to data/digests/ and optionally posts to Discord.
    """
    log.info("tool: generate_weekly_digest(discord=%s)", post_to_discord)
    from eve_agent.weekly_digest import generate_digest, save_digest, post_digest_to_discord
    report = await generate_digest()
    path = await save_digest(report)
    result = {
        "digest_saved_to": str(path),
        "week": report.get("week"),
        "net_pnl": report.get("pnl", {}).get("net_pnl_formatted", "N/A"),
        "report_preview": report["report_text"][:500] + "...",
    }
    if post_to_discord:
        sent = await post_digest_to_discord(report)
        result["discord_sent"] = sent
    return result


# ===========================================================================
# ENTRYPOINT
# ===========================================================================
def main() -> int:
    log.info("Starting EVE Agent MCP server (44 tools).")
    try:
        mcp.run()
    except KeyboardInterrupt:
        log.info("Shutting down.")
    except Exception:
        log.exception("Server crashed.")
        return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())
