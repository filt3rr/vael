"""
P&L Engine — ISK velocity, profitability tracking, compound analysis.

Tracks real profit/loss across activities (trading, manufacturing, exploration)
by analyzing wallet journal entries against memory snapshots.

Exposed as MCP tools:
    get_pnl_summary()           - overall P&L across all activities
    get_isk_velocity()          - rate of ISK growth (per hour/day/week)
    analyze_trading_performance()  - which items are winning vs losing
    get_activity_breakdown()    - income by activity type
    project_isk_growth()        - project future ISK at current velocity
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

from eve_agent import auth, pilot_memory as mem
from eve_agent.esi_client import ESIClient
from eve_agent.sde import get_type


log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Journal entry categorization
# ---------------------------------------------------------------------------
INCOME_TYPES = {
    "bounty_prizes": "PvE / Ratting",
    "agent_mission_reward": "Missions",
    "agent_mission_time_bonus_reward": "Missions",
    "contract_reward": "Contracts",
    "contract_collateral_deposited": "Contracts",
    "market_transaction": "Trading",
    "transaction_tax": "Trading (tax)",
    "brokers_fee": "Trading (fee)",
    "manufacturing": "Industry",
    "industry_job_tax": "Industry (tax)",
    "planetary_import_tax": "Planetary Interaction",
    "planetary_export_tax": "Planetary Interaction",
    "player_donation": "Donation",
    "corp_account_withdrawal": "Corp",
    "insurance": "Insurance",
    "skill_purchase": "Skills",
}

EXPENSE_TYPES = {
    "market_escrow": "Market escrow",
    "transaction_tax": "Tax",
    "brokers_fee": "Fee",
    "industry_job_tax": "Industry tax",
    "reprocessing_tax": "Reprocessing",
    "contract_broker_fee": "Contract fee",
}


def _categorize(ref_type: str) -> str:
    return INCOME_TYPES.get(ref_type, ref_type.replace("_", " ").title())


def _format_isk(value: float) -> str:
    if abs(value) >= 1_000_000_000:
        return f"{value/1_000_000_000:+.2f}B ISK"
    if abs(value) >= 1_000_000:
        return f"{value/1_000_000:+.1f}M ISK"
    return f"{value:+,.0f} ISK"


def _to_ts(date_str: str) -> float:
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return dt.timestamp()
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# Core analysis functions
# ---------------------------------------------------------------------------
async def get_pnl_summary(days: int = 7) -> dict:
    """
    Overall P&L summary for the last N days.
    Breaks down income and expenses by activity type.
    """
    cid = auth.list_characters()[0].character_id
    cutoff = time.time() - (days * 86400)

    async with ESIClient() as esi:
        journal = await esi.get_paginated(
            f"/characters/{cid}/wallet/journal/",
            character_id=cid,
        )

    # Filter to period
    entries = [
        e for e in journal
        if _to_ts(e.get("date", "")) >= cutoff
    ]

    income_by_type: dict[str, float] = {}
    expense_by_type: dict[str, float] = {}
    total_in = 0.0
    total_out = 0.0

    for e in entries:
        amount = e.get("amount", 0.0) or 0.0
        category = _categorize(e.get("ref_type", "unknown"))

        if amount > 0:
            income_by_type[category] = income_by_type.get(category, 0) + amount
            total_in += amount
        elif amount < 0:
            expense_by_type[category] = expense_by_type.get(category, 0) + abs(amount)
            total_out += abs(amount)

    net = total_in - total_out

    # Sort by magnitude
    top_income = sorted(income_by_type.items(), key=lambda x: -x[1])[:8]
    top_expenses = sorted(expense_by_type.items(), key=lambda x: -x[1])[:5]

    return {
        "period_days": days,
        "entries_analyzed": len(entries),
        "total_income": total_in,
        "total_expenses": total_out,
        "net_pnl": net,
        "net_pnl_formatted": _format_isk(net),
        "daily_average": net / days if days > 0 else 0,
        "income_breakdown": [
            {"activity": k, "amount": v, "formatted": _format_isk(v)}
            for k, v in top_income
        ],
        "expense_breakdown": [
            {"activity": k, "amount": v, "formatted": _format_isk(v)}
            for k, v in top_expenses
        ],
        "verdict": (
            "Profitable" if net > 0
            else "Break-even" if abs(net) < 1_000_000
            else "Loss period"
        ),
    }


async def get_isk_velocity() -> dict:
    """
    Calculate ISK growth rate from memory snapshots.
    Returns growth per hour, per day, per week extrapolated.
    """
    history = mem.get_isk_history(50)
    snapshots = history.get("snapshots", [])

    if len(snapshots) < 2:
        # Fall back to current wallet
        from eve_agent.tools.character import get_wallet_balance
        wallet = await get_wallet_balance()
        return {
            "current_isk": wallet.get("isk_balance", 0),
            "note": "Not enough snapshots for velocity calculation. Check back after a few sessions.",
            "snapshots_available": len(snapshots),
        }

    first = snapshots[0]
    last = snapshots[-1]

    try:
        t_first = datetime.strptime(first["time"], "%Y-%m-%d %H:%M UTC").replace(tzinfo=timezone.utc)
        t_last = datetime.strptime(last["time"], "%Y-%m-%d %H:%M UTC").replace(tzinfo=timezone.utc)
        elapsed_hours = (t_last - t_first).total_seconds() / 3600
    except Exception:
        elapsed_hours = 1

    if elapsed_hours < 0.1:
        elapsed_hours = 0.1

    isk_delta = last["isk"] - first["isk"]
    per_hour = isk_delta / elapsed_hours
    per_day = per_hour * 24
    per_week = per_day * 7
    per_month = per_day * 30

    # Milestone projections
    current = last["isk"]
    milestones = {}
    for label, target in [
        ("500M ISK", 500_000_000),
        ("1B ISK", 1_000_000_000),
        ("5B ISK", 5_000_000_000),
        ("10B ISK", 10_000_000_000),
    ]:
        if current < target and per_day > 0:
            days_needed = (target - current) / per_day
            milestones[label] = f"{days_needed:.0f} days at current rate"
        elif current >= target:
            milestones[label] = "Already achieved"

    return {
        "current_isk": current,
        "current_isk_formatted": f"{current:,.0f} ISK",
        "period_measured": f"{elapsed_hours:.1f} hours",
        "total_change": isk_delta,
        "total_change_formatted": _format_isk(isk_delta),
        "per_hour": per_hour,
        "per_day": per_day,
        "per_week": per_week,
        "per_month_projected": per_month,
        "trend": "growing" if per_day > 0 else "shrinking" if per_day < -1_000_000 else "flat",
        "daily_rate_formatted": _format_isk(per_day) + "/day",
        "milestone_projections": milestones,
        "snapshots_used": len(snapshots),
    }


async def analyze_trading_performance(days: int = 14) -> dict:
    """
    Analyze which items are generating the most profit/loss from trading.
    Looks at market transaction history.
    """
    cid = auth.list_characters()[0].character_id
    cutoff = time.time() - (days * 86400)

    async with ESIClient() as esi:
        transactions = await esi.get_paginated(
            f"/characters/{cid}/wallet/transactions/",
            character_id=cid,
        )

    if not transactions:
        return {"note": "No transaction history available.", "days": days}

    recent = [t for t in transactions if _to_ts(t.get("date", "")) >= cutoff]

    # Group by type_id
    by_item: dict[int, dict] = {}
    for tx in recent:
        tid = tx.get("type_id", 0)
        if tid not in by_item:
            by_item[tid] = {"buys": 0.0, "sells": 0.0, "buy_qty": 0, "sell_qty": 0}

        qty = tx.get("quantity", 0)
        unit_price = tx.get("unit_price", 0.0)
        total = qty * unit_price

        if tx.get("is_buy"):
            by_item[tid]["buys"] += total
            by_item[tid]["buy_qty"] += qty
        else:
            by_item[tid]["sells"] += total
            by_item[tid]["sell_qty"] += qty

    # Calculate realized P&L per item (sells - buys)
    results = []
    for tid, data in by_item.items():
        t = get_type(tid)
        name = t["name"] if t else f"Type {tid}"
        # Simple proxy: if we sold more than we bought in the period, net positive
        pnl = data["sells"] - data["buys"]
        results.append({
            "item": name,
            "type_id": tid,
            "buy_volume": data["buy_qty"],
            "sell_volume": data["sell_qty"],
            "buy_spend": data["buys"],
            "sell_revenue": data["sells"],
            "estimated_pnl": pnl,
            "pnl_formatted": _format_isk(pnl),
        })

    results.sort(key=lambda x: -x["estimated_pnl"])

    winners = [r for r in results if r["estimated_pnl"] > 0][:5]
    losers = [r for r in results if r["estimated_pnl"] < 0][:3]
    total_pnl = sum(r["estimated_pnl"] for r in results)

    return {
        "period_days": days,
        "items_traded": len(results),
        "total_transactions": len(recent),
        "estimated_trading_pnl": total_pnl,
        "pnl_formatted": _format_isk(total_pnl),
        "top_winners": winners,
        "loss_items": losers,
        "note": "P&L is estimated from buys vs sells in the period — not accounting for inventory held.",
    }


async def get_activity_breakdown(days: int = 7) -> dict:
    """
    Break down ISK sources by activity: trading, missions, exploration,
    industry, etc. Answers 'what is actually making me money?'
    """
    pnl = await get_pnl_summary(days)

    income = pnl.get("income_breakdown", [])
    total_income = pnl.get("total_income", 1) or 1

    # Add percentage to each
    for item in income:
        item["pct"] = round(item["amount"] / total_income * 100, 1)

    # Primary source
    primary = income[0]["activity"] if income else "Unknown"
    primary_pct = income[0]["pct"] if income else 0

    return {
        "period_days": days,
        "total_income": total_income,
        "net_pnl": pnl.get("net_pnl"),
        "primary_income_source": primary,
        "primary_source_pct": primary_pct,
        "breakdown": income,
        "verdict": pnl.get("verdict"),
        "advice": _activity_advice(primary, primary_pct, total_income / days),
    }


def _activity_advice(primary: str, pct: float, daily_isk: float) -> str:
    """Generate a brief Vael-style observation about income pattern."""
    if daily_isk < 1_000_000:
        return "Income is very low. Need to find a primary activity."
    if pct > 80:
        return f"{primary} is doing all the heavy lifting at {pct:.0f}%. Not a bad thing — but diversify if it ever dries up."
    if pct > 50:
        return f"{primary} is your primary driver. Solid."
    return f"Income is diversified across multiple activities — {primary} leads at {pct:.0f}%."


async def project_isk_growth(
    target_isk: float,
    scenario: str = "current",
) -> dict:
    """
    Project how long to reach a target ISK amount at current or adjusted velocity.
    scenario: 'current', 'optimistic' (2x), 'conservative' (0.5x)
    """
    velocity = await get_isk_velocity()
    current = velocity.get("current_isk", 0)
    daily = velocity.get("per_day", 0)

    if current >= target_isk:
        return {
            "target": target_isk,
            "current": current,
            "already_achieved": True,
            "surplus": current - target_isk,
        }

    if daily <= 0:
        return {
            "target": target_isk,
            "current": current,
            "note": "ISK is not growing. Cannot project without positive velocity.",
            "daily_rate": daily,
        }

    multipliers = {"current": 1.0, "optimistic": 2.0, "conservative": 0.5}
    mult = multipliers.get(scenario, 1.0)
    adjusted_daily = daily * mult
    days_needed = (target_isk - current) / adjusted_daily

    arrival = datetime.now(timezone.utc) + timedelta(days=days_needed)

    return {
        "target_isk": target_isk,
        "target_formatted": f"{target_isk:,.0f} ISK",
        "current_isk": current,
        "gap": target_isk - current,
        "gap_formatted": f"{target_isk - current:,.0f} ISK",
        "scenario": scenario,
        "daily_rate": adjusted_daily,
        "days_to_target": round(days_needed, 1),
        "estimated_arrival": arrival.strftime("%Y-%m-%d"),
        "weeks_to_target": round(days_needed / 7, 1),
    }
