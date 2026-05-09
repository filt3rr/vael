"""
EVE Agent Full Test Suite v4
Run: python tests/test_all_tools.py
"""

from __future__ import annotations
import asyncio, sys, time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Awaitable

# Fix Windows console encoding before any output
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


@dataclass
class R:
    name: str; passed: bool; ms: float; detail: str = ""; error: str = ""

results: list[R] = []

async def t(name: str, coro: Awaitable, v: Callable[[Any], str] | None = None) -> R:
    t0 = time.perf_counter()
    try:
        val = await coro
        ms = (time.perf_counter() - t0) * 1000
        if isinstance(val, dict) and "error" in val:
            r = R(name, False, ms, error=f"Tool error: {val['error']}")
        elif v:
            r = R(name, True, ms, detail=v(val))
        else:
            r = R(name, True, ms, detail=type(val).__name__)
    except Exception as e:
        ms = (time.perf_counter() - t0) * 1000
        r = R(name, False, ms, error=f"{type(e).__name__}: {str(e)[:90]}")
    results.append(r)
    ok = "PASS" if r.passed else "FAIL"
    print(f"  [{ok}] {name:<55} {r.ms:>6.0f}ms  {(r.detail or r.error)[:55]}")
    return r

async def s(fn, *a, **kw):
    return fn(*a, **kw)

from eve_agent.tools import character, market, industry, skills, intel
from eve_agent import auth, pilot_memory as mem
from eve_agent import pnl_engine as pnl
from eve_agent import event_engine as events
from eve_agent.sde import get_type, get_system, search_types, distance_between, get_all_skill_groups


async def main() -> int:
    print("=" * 70)
    print("  EVE Agent -- Full Tool Test Suite v4")
    print("=" * 70)

    chars = auth.list_characters()
    if not chars:
        print("ERROR: No authenticated character.")
        return 1
    char = chars[0]
    print(f"  Character: {char.character_name} (id={char.character_id})")
    print(f"  Scopes:    {len(char.scopes)}\n")

    # SDE
    print("-- SDE ------------------------------------------------------------------")
    await t("get_type Tritanium",        s(get_type, 34),              lambda r: r["name"])
    await t("get_type Rifter",           s(get_type, 587),             lambda r: f"{r['name']} ({r['group_name']})")
    await t("get_system Jita",           s(get_system, 30000142),      lambda r: f"{r['name']} sec={r['security']:.2f}")
    await t("search_types Rifter exact", s(search_types, "Rifter", 3), lambda r: r[0]["name"])
    await t("distance Jita->Amarr",      s(distance_between, 30000142, 30002187), lambda r: f"{r} jumps")
    await t("skill groups",              s(get_all_skill_groups),      lambda r: f"{len(r)} groups")

    # Character
    print("\n-- Character ------------------------------------------------------------")
    await t("get_character_summary",    character.get_character_summary(),    lambda r: f"{r['character_name']} | {r['isk_balance']:,.0f} ISK")
    await t("get_wallet_balance",       character.get_wallet_balance(),       lambda r: r["formatted"])
    await t("get_skill_overview",       character.get_skill_overview(),       lambda r: f"SP={r.get('total_sp',0):,} queue={r.get('queue_length')}")
    await t("get_current_location",     character.get_current_location(),     lambda r: f"{r.get('system_name')} sec={r.get('system_security')} docked={r.get('docked')}")
    await t("get_asset_summary(5)",     character.get_asset_summary(5),       lambda r: f"{r.get('unique_item_types')} types")
    await t("wallet_journal(10)",       character.list_recent_wallet_journal(10), lambda r: f"{r.get('count')} entries")

    # Market
    print("\n-- Market ---------------------------------------------------------------")
    await t("market_price Trit/Jita",   market.get_market_price("Tritanium","Jita"),     lambda r: f"buy={r['best_buy']} sell={r['best_sell']}")
    await t("market_price Rifter/Jita", market.get_market_price("Rifter","Jita"),        lambda r: f"sell={r.get('best_sell',0):,.0f}")
    await t("compare_hubs Tritanium",   market.compare_hub_prices("Tritanium"),          lambda r: f"{len(r['hubs'])} hubs arb={r.get('arbitrage_opportunity') is not None}")
    await t("market_history Trit 14d",  market.get_market_history("Tritanium","Jita",14),lambda r: f"avg={r.get('average_price')} trend={r.get('trend',{}).get('direction')}")
    await t("my_market_orders",         market.get_my_market_orders(),                   lambda r: f"buy={r['open_buy_orders']} sell={r['open_sell_orders']}")

    # Industry
    print("\n-- Industry -------------------------------------------------------------")
    await t("active_industry_jobs",             industry.get_active_industry_jobs(),               lambda r: f"{r.get('count')} jobs")
    await t("blueprint_info Rifter",            industry.get_blueprint_info("Rifter"),             lambda r: f"{len(r.get('materials_per_run',[]))} mats time={r.get('base_manufacturing_time_formatted')}")
    await t("mfg_cost Rifter 1 run me=0",      industry.calculate_manufacturing_cost("Rifter",1,0),   lambda r: f"cost={r.get('material_cost_total',0):,.0f} profit={r.get('estimated_profit',0):,.0f}")
    await t("mfg_cost Rifter 10 runs me=10",   industry.calculate_manufacturing_cost("Rifter",10,10), lambda r: f"ok={r.get('profitable')}")

    # Skills
    print("\n-- Skills ---------------------------------------------------------------")
    await t("can_i_fly Rifter",             skills.can_i_fly("Rifter"),                  lambda r: f"can_fly={r.get('can_fly')} missing={len(r.get('skills_missing_or_too_low',[]))}")
    await t("can_i_fly Corax",              skills.can_i_fly("Corax"),                   lambda r: f"can_fly={r.get('can_fly')}")
    await t("training_time Cyber->4",       skills.calculate_training_time("Cybernetics",4,30.0), lambda r: r.get("estimated_time",{}).get("formatted","?") if not r.get("already_trained") else f"already lvl{r.get('current_level')}")
    await t("get_skill_queue",              skills.get_skill_queue(),                    lambda r: f"{r.get('queue_length')} skills {r.get('queue_total_days')}d")
    await t("suggest_next_skills(5)",       skills.suggest_next_skills(5),              lambda r: f"{len(r.get('top_suggestions',[]))} suggestions")

    # Intel
    print("\n-- Intel (zKillboard) ---------------------------------------------------")
    await t("system_danger Uedama",     intel.get_system_danger("Uedama"),                lambda r: f"danger={r.get('danger_rating')}/10 kills={r.get('kills_last_7d')}")
    await t("system_danger Jita",       intel.get_system_danger("Jita"),                  lambda r: f"danger={r.get('danger_rating')}/10")
    await t("recent_kills Jita 5",      intel.get_recent_kills_in_system("Jita",5),       lambda r: f"{r.get('count')} kills")
    await t("should_i_undock 50M",      intel.should_i_undock(50_000_000),                lambda r: f"danger={r.get('danger_rating')} {r.get('recommendation','')[:30]}")
    await t("regional_kills The Forge", intel.get_regional_kill_activity("The Forge",3),  lambda r: f"kills={r.get('kills_last_7d')} isk={r.get('total_isk_destroyed')}")
    await t("char_intel CCP Falcon",    intel.get_character_intel("CCP Falcon"),          lambda r: f"{r.get('character_name')} corp={r.get('corporation')}")

    # Pilot Memory
    print("\n-- Pilot Memory ---------------------------------------------------------")
    await t("read_pilot_memory()",          s(mem.read_pilot_memory),                    lambda r: f"{len(r)} keys")
    await t("write_pilot_memory goals",     s(mem.write_pilot_memory, "goals", "test_key", "test value"), lambda r: r.get("status"))
    await t("append_pilot_memory milestones", s(mem.append_pilot_memory, "milestones", "Test milestone entry"), lambda r: r.get("status"))
    await t("log_isk_snapshot",             s(mem.log_isk_snapshot, 247_000_000.0, "test"), lambda r: r.get("status"))
    await t("get_isk_history(10)",          s(mem.get_isk_history, 10),                  lambda r: f"{len(r.get('snapshots',[]))} snapshots trend={r.get('trend','?')}")

    # P&L Engine
    print("\n-- P&L Engine -----------------------------------------------------------")
    await t("get_pnl_summary(7d)",          pnl.get_pnl_summary(7),               lambda r: f"net={r.get('net_pnl_formatted')} verdict={r.get('verdict')}")
    await t("get_isk_velocity",             pnl.get_isk_velocity(),               lambda r: f"daily={r.get('daily_rate_formatted','?')} trend={r.get('trend','?')}")
    await t("analyze_trading(14d)",         pnl.analyze_trading_performance(14),  lambda r: f"{r.get('items_traded',0)} items pnl={r.get('pnl_formatted','?')}")
    await t("get_activity_breakdown(7d)",   pnl.get_activity_breakdown(7),        lambda r: f"primary={r.get('primary_income_source','?')} {r.get('primary_source_pct',0):.0f}%")
    await t("project_isk_growth(500M)",     pnl.project_isk_growth(500_000_000),  lambda r: f"days={r.get('days_to_target','already')} achieved={r.get('already_achieved',False)}")

    # Event Engine
    print("\n-- Event Watches --------------------------------------------------------")
    await t("list_watches",     s(events.list_watches),                         lambda r: f"{r.get('count',0)} watches")
    await t("add_watch price",  s(events.add_watch, "price_below", "test_trit_watch", {"item":"Tritanium","threshold":2.0,"hub":"Jita"}), lambda r: r.get("status","?"))
    await t("list_watches(2)",  s(events.list_watches),                         lambda r: f"{r.get('count',0)} watches after add")
    await t("remove_watch",     s(events.remove_watch, "test_trit_watch"),      lambda r: r.get("status","?"))
    await t("list_watches(1)",  s(events.list_watches),                         lambda r: f"{r.get('count',0)} watches after remove")

    # Discord
    print("\n-- Discord --------------------------------------------------------------")
    from eve_agent.discord_alerts import _is_configured, test_webhook
    await t("discord configured?", s(_is_configured),  lambda r: "YES - webhook set" if r else "NO - add DISCORD_WEBHOOK_URL to .env")

    # Summary
    passed = [r for r in results if r.passed]
    failed = [r for r in results if not r.passed]
    total_ms = sum(r.ms for r in results)

    print("\n" + "=" * 70)
    print(f"  {len(passed)} PASSED  {len(failed)} FAILED  {len(results)} total  {total_ms/1000:.1f}s")
    print("=" * 70)

    if failed:
        print("\n  Failed tests:")
        for r in failed:
            print(f"    FAIL  {r.name}")
            print(f"          {r.error}")
        print()
    else:
        print("\n  All tools operational\n")

    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
