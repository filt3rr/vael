"""
Skill planning MCP tools.

Help with:
  - "How long until skill X at level Y?"
  - "Can I fly a Tempest?"
  - "What do I need to train to fly that?"
  - Skill queue analysis
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from eve_agent import auth
from eve_agent.esi_client import ESIClient
from eve_agent.sde import _conn, get_type, search_types


log = logging.getLogger(__name__)


# Skill points required for each level (cumulative SP at level N)
# Formula: SP = 250 * rank * 5.66^(level - 1), but EVE rounds these
SP_PER_LEVEL_MULTIPLIER = {
    1: 250,
    2: 1414,
    3: 8000,
    4: 45255,
    5: 256000,
}


def _current_character_id() -> int:
    chars = auth.list_characters()
    if not chars:
        raise RuntimeError("No authenticated character.")
    return chars[0].character_id


def _resolve_type_id(name_or_id: str) -> Optional[int]:
    s = str(name_or_id).strip()
    if s.isdigit():
        return int(s)
    matches = search_types(s, limit=10)
    if not matches:
        return None
    for m in matches:
        if m["name"].lower() == s.lower():
            return m["type_id"]
    return matches[0]["type_id"]


def _get_skill_rank(skill_type_id: int) -> int:
    """Get the training time multiplier (rank) for a skill."""
    row = _conn().execute(
        """
        SELECT valueInt, valueFloat
        FROM dgmTypeAttributes
        WHERE typeID = ? AND attributeID = 275
        """,
        (skill_type_id,),
    ).fetchone()
    if not row:
        return 1
    val = row[0] if row[0] is not None else row[1]
    return int(val) if val else 1


def _sp_for_level(skill_rank: int, level: int) -> int:
    """SP required at a given level for a skill of given rank."""
    if level < 1:
        return 0
    if level > 5:
        level = 5
    return SP_PER_LEVEL_MULTIPLIER[level] * skill_rank


def _get_ship_prerequisites(ship_type_id: int) -> list[dict]:
    """Return required skills to fly a ship (skill_type_id and required level)."""
    # Skill requirements are stored as attributes 182/183/184/277/1285/1289/1290
    # paired with 277/278/279/1286/1287/1288 for the level.
    # Simpler: dgmTypeAttributes with skill attribute IDs
    skill_attrs = [182, 183, 184, 1285, 1289, 1290]
    level_attrs = [277, 278, 279, 1286, 1287, 1288]

    skills_required = []
    for skill_attr, level_attr in zip(skill_attrs, level_attrs):
        skill_row = _conn().execute(
            """
            SELECT valueInt, valueFloat FROM dgmTypeAttributes
            WHERE typeID = ? AND attributeID = ?
            """,
            (ship_type_id, skill_attr),
        ).fetchone()
        if not skill_row:
            continue

        skill_id = int(skill_row[0] or skill_row[1] or 0)
        if not skill_id:
            continue

        level_row = _conn().execute(
            """
            SELECT valueInt, valueFloat FROM dgmTypeAttributes
            WHERE typeID = ? AND attributeID = ?
            """,
            (ship_type_id, level_attr),
        ).fetchone()
        level = int(level_row[0] or level_row[1] or 1) if level_row else 1

        skill_info = get_type(skill_id)
        skills_required.append({
            "skill_id": skill_id,
            "skill_name": skill_info["name"] if skill_info else f"Skill {skill_id}",
            "required_level": level,
        })

    return skills_required


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
async def calculate_training_time(
    skill: str,
    target_level: int,
    sp_per_minute: float = 30.0,
) -> dict:
    """
    Calculate how long it would take to train a skill to a target level
    starting from the character's current level.

    sp_per_minute is your training rate. Default 30 SP/min is typical for
    a new character with attribute remaps. Improves with implants/remap.
    """
    cid = _current_character_id()
    skill_type_id = _resolve_type_id(skill)
    if not skill_type_id:
        return {"error": f"Could not resolve skill '{skill}'."}

    skill_info = get_type(skill_type_id)
    skill_name = skill_info["name"] if skill_info else f"Skill {skill_type_id}"
    rank = _get_skill_rank(skill_type_id)

    async with ESIClient() as esi:
        skills_data = await esi.get(
            f"/characters/{cid}/skills/", character_id=cid
        )

    # Find current level
    current_level = 0
    current_sp = 0
    for s in skills_data.get("skills", []):
        if s["skill_id"] == skill_type_id:
            current_level = s.get("trained_skill_level", 0)
            current_sp = s.get("skillpoints_in_skill", 0)
            break

    if current_level >= target_level:
        return {
            "skill": skill_name,
            "current_level": current_level,
            "target_level": target_level,
            "already_trained": True,
        }

    sp_at_target = _sp_for_level(rank, target_level)
    sp_needed = max(0, sp_at_target - current_sp)
    minutes = sp_needed / sp_per_minute
    days, rem = divmod(int(minutes), 1440)
    hours, mins = divmod(rem, 60)

    return {
        "skill": skill_name,
        "skill_rank": rank,
        "current_level": current_level,
        "current_sp": current_sp,
        "target_level": target_level,
        "sp_required_at_target": sp_at_target,
        "sp_to_train": sp_needed,
        "training_rate_sp_per_min": sp_per_minute,
        "estimated_time": {
            "days": days,
            "hours": hours,
            "minutes": mins,
            "total_minutes": int(minutes),
            "formatted": f"{days}d {hours}h {mins}m",
        },
    }


async def can_i_fly(ship: str) -> dict:
    """
    Check if the character meets the skill prerequisites to fly a ship.
    Returns a list of any missing/under-trained skills with how much
    more training each requires.
    """
    cid = _current_character_id()
    ship_type_id = _resolve_type_id(ship)
    if not ship_type_id:
        return {"error": f"Could not resolve ship '{ship}'."}

    ship_info = get_type(ship_type_id)
    ship_name = ship_info["name"] if ship_info else f"Type {ship_type_id}"

    prereqs = _get_ship_prerequisites(ship_type_id)
    if not prereqs:
        return {
            "ship": ship_name,
            "error": "No skill prerequisites found (or item is not a flyable ship).",
        }

    async with ESIClient() as esi:
        skills_data = await esi.get(
            f"/characters/{cid}/skills/", character_id=cid
        )

    my_skills = {
        s["skill_id"]: s.get("trained_skill_level", 0)
        for s in skills_data.get("skills", [])
    }

    missing = []
    have = []
    for req in prereqs:
        my_level = my_skills.get(req["skill_id"], 0)
        if my_level >= req["required_level"]:
            have.append({**req, "my_level": my_level})
        else:
            missing.append({
                **req,
                "my_level": my_level,
                "levels_needed": req["required_level"] - my_level,
            })

    return {
        "ship": ship_name,
        "can_fly": len(missing) == 0,
        "skills_missing_or_too_low": missing,
        "skills_already_met": have,
        "summary": (
            f"Yes — you can fly the {ship_name}."
            if not missing
            else f"Need to train {len(missing)} more skill(s) before flying the {ship_name}."
        ),
    }


async def get_skill_queue() -> dict:
    """Return the character's full skill training queue with resolved names."""
    cid = _current_character_id()
    async with ESIClient() as esi:
        queue = await esi.get(
            f"/characters/{cid}/skillqueue/", character_id=cid
        )

    enriched = []
    for q in queue:
        skill = get_type(q["skill_id"])
        enriched.append({
            "skill": skill["name"] if skill else f"Skill {q['skill_id']}",
            "to_level": q.get("finished_level"),
            "level_start_sp": q.get("level_start_sp"),
            "level_end_sp": q.get("level_end_sp"),
            "training_start": q.get("start_date"),
            "training_end": q.get("finish_date"),
            "queue_position": q.get("queue_position"),
        })

    # Total queue duration
    if enriched and enriched[-1].get("training_end") and enriched[0].get("training_start"):
        try:
            start = datetime.fromisoformat(enriched[0]["training_start"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(enriched[-1]["training_end"].replace("Z", "+00:00"))
            queue_days = (end - start).total_seconds() / 86400
        except Exception:
            queue_days = None
    else:
        queue_days = None

    return {
        "queue_length": len(enriched),
        "queue_total_days": round(queue_days, 1) if queue_days else None,
        "queue": enriched,
    }


async def suggest_next_skills(top_n: int = 5) -> dict:
    """
    Suggest skills the character should consider training based on common
    high-impact early skills for new pilots.
    """
    cid = _current_character_id()
    async with ESIClient() as esi:
        skills_data = await esi.get(
            f"/characters/{cid}/skills/", character_id=cid
        )

    my_skills = {
        s["skill_id"]: s.get("trained_skill_level", 0)
        for s in skills_data.get("skills", [])
    }

    # Common high-value early skills (skill_id, name, target_level, why)
    candidates = [
        (3327, "Cybernetics", 4, "Required for +4 implants — biggest training-rate boost"),
        (3300, "Gunnery", 5, "Foundation for all turret weapons"),
        (3380, "CPU Management", 5, "More CPU = better fittings"),
        (3413, "Power Grid Management", 5, "More PG = better fittings"),
        (16622, "Capacitor Management", 4, "Larger capacitor"),
        (3424, "Capacitor Systems Operation", 4, "Faster cap recharge"),
        (3432, "Navigation", 5, "Faster sub-warp speed everywhere"),
        (3449, "Spaceship Command", 5, "Required for many ships"),
        (3393, "Mechanics", 4, "More structure HP"),
        (3392, "Hull Upgrades", 5, "Reactive armor mods, plates, etc."),
        (12365, "Long Range Targeting", 4, "Lock at greater range"),
        (3428, "Targeting", 5, "Lock more targets simultaneously"),
        (3300, "Drones", 5, "Drone bandwidth/control range"),
        (3327, "Electronic Warfare", 3, "Counter common tackle"),
    ]

    suggestions = []
    for skill_id, name, target, why in candidates:
        my_level = my_skills.get(skill_id, 0)
        if my_level < target:
            suggestions.append({
                "skill": name,
                "skill_id": skill_id,
                "current_level": my_level,
                "suggested_level": target,
                "rationale": why,
            })

    return {
        "total_sp": skills_data.get("total_sp"),
        "unallocated_sp": skills_data.get("unallocated_sp", 0),
        "top_suggestions": suggestions[:top_n],
        "note": (
            "These are common high-value foundational skills. "
            "For specific ship/role goals use can_i_fly() to see exact gaps."
        ),
    }