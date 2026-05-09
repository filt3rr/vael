"""
Weekly digest — auto-generated summary report.

Generates a comprehensive week-in-review every Sunday (or on demand).
Covers: ISK performance, training progress, market activity, notable events.
Saves to data/digests/ and can post to Discord.

Run:
    python -m eve_agent.weekly_digest
    python -m eve_agent.weekly_digest --discord
"""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from eve_agent.config import DATA_DIR, ensure_dirs
from eve_agent import pilot_memory as mem
from eve_agent import auth


log = logging.getLogger(__name__)
DIGESTS_DIR = DATA_DIR / "digests"


async def generate_digest() -> dict:
    """
    Pull all relevant data and compile the weekly digest.
    Returns a dict with all sections and the formatted text.
    """
    from eve_agent.tools.character import (
        get_character_summary, get_skill_overview, get_wallet_balance
    )
    from eve_agent.tools.market import get_my_market_orders
    from eve_agent.tools.industry import get_active_industry_jobs
    from eve_agent.tools.skills import get_skill_queue, suggest_next_skills
    from eve_agent.pnl_engine import (
        get_pnl_summary, get_isk_velocity, get_activity_breakdown
    )

    now = datetime.now(timezone.utc)
    week_str = now.strftime("Week of %B %d, %Y")

    sections = {}

    # Pull data
    try: sections["character"] = await get_character_summary()
    except Exception as e: sections["character"] = {"error": str(e)}

    try: sections["wallet"] = await get_wallet_balance()
    except Exception as e: sections["wallet"] = {"error": str(e)}

    try: sections["skills"] = await get_skill_overview()
    except Exception as e: sections["skills"] = {"error": str(e)}

    try: sections["queue"] = await get_skill_queue()
    except Exception as e: sections["queue"] = {"error": str(e)}

    try: sections["orders"] = await get_my_market_orders()
    except Exception as e: sections["orders"] = {"error": str(e)}

    try: sections["jobs"] = await get_active_industry_jobs()
    except Exception as e: sections["jobs"] = {"error": str(e)}

    try: sections["pnl"] = await get_pnl_summary(days=7)
    except Exception as e: sections["pnl"] = {"error": str(e)}

    try: sections["velocity"] = await get_isk_velocity()
    except Exception as e: sections["velocity"] = {"error": str(e)}

    try: sections["activity"] = await get_activity_breakdown(days=7)
    except Exception as e: sections["activity"] = {"error": str(e)}

    try: sections["suggestions"] = await suggest_next_skills(3)
    except Exception as e: sections["suggestions"] = {"error": str(e)}

    memory = mem.read_pilot_memory()

    # Compose text report
    report = _compose_report(week_str, sections, memory)
    sections["report_text"] = report
    sections["week"] = week_str
    sections["generated_at"] = now.isoformat()

    return sections


def _compose_report(week_str: str, s: dict, memory: dict) -> str:
    """Compose the full weekly digest as formatted text."""
    lines = []
    a = lines.append

    char = s.get("character", {})
    wallet = s.get("wallet", {})
    skills = s.get("skills", {})
    pnl = s.get("pnl", {})
    velocity = s.get("velocity", {})
    activity = s.get("activity", {})
    orders = s.get("orders", {})
    jobs = s.get("jobs", {})
    queue = s.get("queue", {})
    suggestions = s.get("suggestions", {})

    a(f"# VAEL WEEKLY DIGEST")
    a(f"## {week_str}")
    a(f"*Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}*")
    a("")

    # --- PILOT STATUS ---
    a("---")
    a("## PILOT STATUS")
    if "error" not in char:
        a(f"**Character:** {char.get('character_name', 'Unknown')}")
        a(f"**Location:** {char.get('location', 'Unknown')}")
        a(f"**Ship:** {char.get('current_ship', 'Unknown')}")
        a(f"**Security Status:** {char.get('security_status', 0):.3f}")
    a("")

    # --- ISK PERFORMANCE ---
    a("---")
    a("## ISK PERFORMANCE (Last 7 Days)")
    if "error" not in pnl:
        net = pnl.get("net_pnl", 0)
        a(f"**Net P&L:** {pnl.get('net_pnl_formatted', 'N/A')}")
        a(f"**Total Income:** {pnl.get('total_income', 0):,.0f} ISK")
        a(f"**Total Expenses:** {pnl.get('total_expenses', 0):,.0f} ISK")
        a(f"**Verdict:** {pnl.get('verdict', 'Unknown')}")
        a("")
        if pnl.get("income_breakdown"):
            a("**Income by activity:**")
            for item in pnl["income_breakdown"][:5]:
                a(f"  - {item['activity']}: {item['formatted']}")
    a("")

    if "error" not in velocity:
        a(f"**Daily rate:** {velocity.get('daily_rate_formatted', 'N/A')}")
        a(f"**Current wallet:** {velocity.get('current_isk_formatted', 'N/A')}")
        milestones = velocity.get("milestone_projections", {})
        if milestones:
            a("")
            a("**Milestone projections:**")
            for label, eta in milestones.items():
                a(f"  - {label}: {eta}")
    a("")

    # --- MARKET ---
    a("---")
    a("## MARKET ACTIVITY")
    if "error" not in orders:
        a(f"**Open buy orders:** {orders.get('open_buy_orders', 0)}")
        a(f"**Open sell orders:** {orders.get('open_sell_orders', 0)}")
        a(f"**ISK in buy orders:** {orders.get('isk_locked_in_buy_orders', 0):,.0f} ISK")
        a(f"**Sell listing value:** {orders.get('total_sell_listing_value', 0):,.0f} ISK")
    a("")

    # --- INDUSTRY ---
    a("---")
    a("## INDUSTRY")
    if "error" not in jobs:
        a(f"**Active jobs:** {jobs.get('count', 0)}")
        for job in jobs.get("jobs", [])[:3]:
            status = job.get("status", "")
            a(f"  - {job.get('activity', '')}: {job.get('product', 'Unknown')} x{job.get('runs', 1)} [{status}]")
    a("")

    # --- SKILLS ---
    a("---")
    a("## SKILL PROGRESSION")
    if "error" not in skills:
        a(f"**Total SP:** {skills.get('total_sp', 0):,}")
        a(f"**Unallocated SP:** {skills.get('unallocated_sp', 0):,}")
        a(f"**Skills trained:** {skills.get('skills_count', 0)}")
        a(f"**Queue length:** {skills.get('queue_length', 0)} skills")

    if "error" not in queue:
        days_left = queue.get("queue_total_days", 0) or 0
        a(f"**Queue duration:** {days_left:.1f} days remaining")
        for entry in queue.get("queue", [])[:3]:
            a(f"  - {entry.get('skill')} to Level {entry.get('to_level')} (ends {entry.get('training_end', 'unknown')[:10]})")
    a("")

    if "error" not in suggestions:
        a("**Vael recommends training next:**")
        for s_item in suggestions.get("top_suggestions", [])[:3]:
            a(f"  - {s_item.get('skill')} to Level {s_item.get('suggested_level')}: {s_item.get('rationale', '')}")
    a("")

    # --- GOALS ---
    goals_data = memory.get("goals", {})
    if goals_data:
        a("---")
        a("## ACTIVE GOALS")
        for key, entry in list(goals_data.items())[:5]:
            if isinstance(entry, dict):
                a(f"  - **{key}:** {entry.get('value', '')}")
    a("")

    # --- RECENT MILESTONES ---
    milestones_data = memory.get("milestones", {})
    milestone_log = milestones_data.get("log", [])
    if milestone_log:
        a("---")
        a("## RECENT MILESTONES")
        for m in milestone_log[-5:]:
            a(f"  - [{m.get('time', '')}] {m.get('entry', '')}")
    a("")

    # --- VAEL'S ASSESSMENT ---
    a("---")
    a("## VAEL'S ASSESSMENT")
    a(_generate_assessment(pnl, velocity, skills, queue))
    a("")
    a("---")
    a("*Report generated by Vael — EVE Online MCP Agent*")

    return "\n".join(lines)


def _generate_assessment(pnl: dict, velocity: dict, skills: dict, queue: dict) -> str:
    """Generate a brief Vael-style weekly assessment."""
    points = []

    net = pnl.get("net_pnl", 0)
    if net > 50_000_000:
        points.append(f"Strong week financially — {pnl.get('net_pnl_formatted', '')} net. Keep the pressure on.")
    elif net > 0:
        points.append(f"Profitable week, {pnl.get('net_pnl_formatted', '')} net. Small but moving in the right direction.")
    elif net < 0:
        points.append(f"Lost ISK this week ({pnl.get('net_pnl_formatted', '')}). Worth understanding why before repeating the same activity.")

    sp = skills.get("total_sp", 0)
    if sp < 5_000_000:
        points.append(f"At {sp:,} SP you're still early. Skill training is your most valuable asset right now — don't let the queue sit empty.")

    queue_days = queue.get("queue_total_days", 0) or 0
    if queue_days < 1:
        points.append("Queue is nearly empty. Top priority this week: plan the next 30 days of training.")
    elif queue_days < 3:
        points.append(f"Queue is short at {queue_days:.1f} days. Consider queuing more skills.")

    daily = velocity.get("per_day", 0)
    if daily > 10_000_000:
        points.append(f"ISK velocity is solid at {velocity.get('daily_rate_formatted', '')}.")
    elif daily > 0:
        points.append(f"ISK growing slowly at {velocity.get('daily_rate_formatted', '')}. Identify the highest-return activity and double down.")

    if not points:
        points.append("Steady week. Keep building.")

    return " ".join(points)


async def save_digest(report: dict) -> Path:
    """Save the digest to disk."""
    ensure_dirs()
    DIGESTS_DIR.mkdir(parents=True, exist_ok=True)

    filename = f"digest_{datetime.now(timezone.utc).strftime('%Y_%m_%d')}.md"
    path = DIGESTS_DIR / filename
    path.write_text(report["report_text"], encoding="utf-8")
    log.info("Digest saved to %s", path)
    return path


async def post_digest_to_discord(report: dict) -> bool:
    """Post a summary of the digest to Discord."""
    from eve_agent.discord_alerts import alert_rich

    pnl = report.get("pnl", {})
    velocity = report.get("velocity", {})
    skills = report.get("skills", {})

    fields = {}
    if "error" not in pnl:
        fields["Net P&L"] = pnl.get("net_pnl_formatted", "N/A")
        fields["Verdict"] = pnl.get("verdict", "N/A")
    if "error" not in velocity:
        fields["ISK/day"] = velocity.get("daily_rate_formatted", "N/A")
        fields["Wallet"] = velocity.get("current_isk_formatted", "N/A")
    if "error" not in skills:
        fields["Total SP"] = f"{skills.get('total_sp', 0):,}"

    char_name = report.get("character", {}).get("character_name", "FILT3R")

    return alert_rich(
        title=f"Weekly Digest | {char_name} | {report.get('week', '')}",
        description=report.get("pnl", {}).get("verdict", "Report generated."),
        color="info",
        fields=fields,
        footer="Vael Weekly Digest | Full report saved locally",
    )


async def run(post_discord: bool = False) -> int:
    ensure_dirs()
    chars = auth.list_characters()
    if not chars:
        print("No authenticated character.")
        return 1

    print(f"Generating weekly digest for {chars[0].character_name}...")
    report = await generate_digest()
    path = await save_digest(report)
    print(f"Digest saved: {path}")
    print()
    print(report["report_text"])

    if post_discord:
        success = await post_digest_to_discord(report)
        print(f"\nDiscord post: {'sent' if success else 'failed'}")

    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    post_discord = "--discord" in sys.argv
    return asyncio.run(run(post_discord))


if __name__ == "__main__":
    sys.exit(main())
