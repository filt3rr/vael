"""
Fittings and ship equipment tools.

EVE's ESI doesn't expose "what's currently in slot X" directly.
We work around this two ways:

1. get_saved_fittings() — reads fittings you've saved in-game via the
   fitting window (Fitting -> Save). These are named loadouts with full
   slot detail.

2. get_active_ship_equipment() — reads your assets and filters to items
   with location flags that indicate they're fitted to your current ship
   (flags like HiSlot0-7, MedSlot0-7, LoSlot0-7, RigSlot0-3, SubSystemSlot0-3,
   DroneBay, CargoHold). Cross-references with your current ship ID.

3. recommend_exploration_fit() — returns Vael's recommended Heron fit
   for the character's current skill level and budget.
"""

from __future__ import annotations

import logging
from typing import Optional

from eve_agent import auth
from eve_agent.esi_client import ESIClient
from eve_agent.sde import get_type


log = logging.getLogger(__name__)


# ESI asset location flags for fitted items
# https://esi.evetech.net/ui/#/Assets
FITTED_FLAGS = {
    # High slots
    "HiSlot0", "HiSlot1", "HiSlot2", "HiSlot3",
    "HiSlot4", "HiSlot5", "HiSlot6", "HiSlot7",
    # Mid slots
    "MedSlot0", "MedSlot1", "MedSlot2", "MedSlot3",
    "MedSlot4", "MedSlot5", "MedSlot6", "MedSlot7",
    # Low slots
    "LoSlot0", "LoSlot1", "LoSlot2", "LoSlot3",
    "LoSlot4", "LoSlot5", "LoSlot6", "LoSlot7",
    # Rigs
    "RigSlot0", "RigSlot1", "RigSlot2",
    # Subsystems (T3 cruisers)
    "SubSystemSlot0", "SubSystemSlot1", "SubSystemSlot2", "SubSystemSlot3",
    # Drone bay and cargo are not "fitted" but useful to show
    "DroneBay",
    "Cargo",
}

SLOT_CATEGORIES = {
    "Hi": "High slots",
    "Med": "Mid slots",
    "Lo": "Low slots",
    "Rig": "Rig slots",
    "SubSystem": "Subsystems",
    "DroneBay": "Drone bay",
    "Cargo": "Cargo hold",
}


def _slot_category(flag: str) -> str:
    for prefix, label in SLOT_CATEGORIES.items():
        if flag.startswith(prefix):
            return label
    return "Other"


def _current_character_id() -> int:
    chars = auth.list_characters()
    if not chars:
        raise RuntimeError("No authenticated character.")
    return chars[0].character_id


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
async def get_saved_fittings() -> dict:
    """
    Return all fittings saved in-game via the fitting window.
    These are named loadouts with full slot detail.
    Requires esi-fittings.read_fittings.v1 scope.
    """
    cid = _current_character_id()

    async with ESIClient() as esi:
        try:
            fittings = await esi.get(
                f"/characters/{cid}/fittings/",
                character_id=cid,
            )
        except Exception as e:
            return {"error": f"Could not read fittings: {e}"}

    if not fittings:
        return {
            "count": 0,
            "fittings": [],
            "note": (
                "No saved fittings found. Save a fitting in-game via "
                "the Fitting window (Alt+F) -> Save Fitting."
            ),
        }

    enriched = []
    for fit in fittings:
        ship_type = get_type(fit.get("ship_type_id", 0))
        items_by_slot: dict[str, list] = {}

        for item in fit.get("items", []):
            flag = item.get("flag", "Other")
            category = _slot_category(flag)
            if category not in items_by_slot:
                items_by_slot[category] = []
            type_info = get_type(item.get("type_id", 0))
            items_by_slot[category].append({
                "module": type_info["name"] if type_info else f"Type {item.get('type_id')}",
                "quantity": item.get("quantity", 1),
                "flag": flag,
            })

        enriched.append({
            "fitting_id": fit.get("fitting_id"),
            "name": fit.get("name", "Unnamed"),
            "ship": ship_type["name"] if ship_type else f"Type {fit.get('ship_type_id')}",
            "ship_type_id": fit.get("ship_type_id"),
            "description": fit.get("description", ""),
            "slots": items_by_slot,
        })

    return {
        "count": len(enriched),
        "fittings": enriched,
    }


async def get_active_ship_equipment() -> dict:
    """
    Read what's currently equipped on your active ship by checking
    asset location flags. Returns modules by slot type.

    Note: ESI doesn't tell us which specific ship the items are on,
    so this returns all fitted items across all ships in your current
    location. If you're only flying one ship right now, this is your fit.
    """
    cid = _current_character_id()

    async with ESIClient() as esi:
        # Get current ship info
        ship_info = await esi.get(
            f"/characters/{cid}/ship/",
            character_id=cid,
        )
        location = await esi.get(
            f"/characters/{cid}/location/",
            character_id=cid,
        )

        # Get all assets
        assets = await esi.get_paginated(
            f"/characters/{cid}/assets/",
            character_id=cid,
        )

    current_ship_id = ship_info.get("ship_item_id")
    ship_type = get_type(ship_info.get("ship_type_id", 0))
    ship_name = ship_type["name"] if ship_type else "Unknown ship"

    # Filter to items fitted to the current ship
    # Items fitted to a ship have location_id == ship's item_id
    fitted = [
        a for a in assets
        if a.get("location_id") == current_ship_id
        and a.get("location_flag") in FITTED_FLAGS
    ]

    # Also get cargo
    cargo = [
        a for a in assets
        if a.get("location_id") == current_ship_id
        and a.get("location_flag") == "Cargo"
    ]

    # Group by slot
    by_slot: dict[str, list] = {}
    for item in fitted:
        flag = item.get("location_flag", "Unknown")
        category = _slot_category(flag)
        if category not in by_slot:
            by_slot[category] = []
        type_info = get_type(item.get("type_id", 0))
        by_slot[category].append({
            "module": type_info["name"] if type_info else f"Type {item.get('type_id')}",
            "type_id": item.get("type_id"),
            "flag": flag,
            "quantity": item.get("quantity", 1),
            "category": type_info.get("category_name") if type_info else None,
        })

    # Sort slots in logical order
    slot_order = [
        "High slots", "Mid slots", "Low slots",
        "Rig slots", "Subsystems", "Drone bay",
    ]
    ordered = {k: by_slot[k] for k in slot_order if k in by_slot}
    for k in by_slot:
        if k not in ordered:
            ordered[k] = by_slot[k]

    # Cargo summary
    cargo_items = []
    for item in cargo[:20]:
        type_info = get_type(item.get("type_id", 0))
        cargo_items.append({
            "item": type_info["name"] if type_info else f"Type {item.get('type_id')}",
            "quantity": item.get("quantity", 1),
        })

    total_fitted = sum(len(v) for v in by_slot.values())

    if total_fitted == 0:
        return {
            "ship": ship_name,
            "ship_type_id": ship_info.get("ship_type_id"),
            "ship_item_id": current_ship_id,
            "fitted_modules": {},
            "cargo": cargo_items,
            "note": (
                "No fitted modules detected. This can happen if you're docked "
                "and the ship is in your hangar rather than active, or if the "
                "ESI cache hasn't updated since your last fitting change. "
                "Try undocking and redocking, or save your fitting in-game "
                "and use get_saved_fittings() instead."
            ),
        }

    return {
        "ship": ship_name,
        "ship_type_id": ship_info.get("ship_type_id"),
        "ship_item_id": current_ship_id,
        "fitted_modules": ordered,
        "cargo_preview": cargo_items[:10],
        "total_modules_fitted": total_fitted,
    }


async def recommend_exploration_fit(budget_isk: float = 50_000_000) -> dict:
    """
    Recommend a Heron exploration fit appropriate for FILT3R's skill level.
    Returns modules with Jita prices and a total cost estimate.
    Explains the role of each module.
    """
    cid = _current_character_id()

    async with ESIClient() as esi:
        skills_data = await esi.get(
            f"/characters/{cid}/skills/",
            character_id=cid,
        )

    my_skills = {
        s["skill_id"]: s.get("trained_skill_level", 0)
        for s in skills_data.get("skills", [])
    }

    # Check key exploration skills
    astrometrics = my_skills.get(3412, 0)       # Astrometrics
    astr_rangefinding = my_skills.get(25739, 0) # Astrometric Rangefinding
    astr_acquisition = my_skills.get(3413, 0)   # Astrometric Acquisition — wait, wrong ID
    hacking = my_skills.get(21718, 0)           # Hacking
    archaeology = my_skills.get(40176, 0)       # Archaeology
    cloaking = my_skills.get(11579, 0)          # Cloaking

    # Standard T1 Heron exploration fit
    # Slots: 4 high, 4 mid, 2 low, 3 rigs
    fit = {
        "ship": "Heron",
        "ship_type_id": 605,
        "philosophy": (
            "The Heron is the best T1 exploration frigate. "
            "Fit for maximum scan strength, hacking ability, and survivability. "
            "This fit can run Data and Relic sites in highsec and lowsec."
        ),
        "high_slots": [
            {
                "module": "Core Probe Launcher I",
                "role": "Launches Core Scanner Probes for scanning signatures",
                "required": True,
                "approx_price_isk": 15_000,
            },
            {
                "module": "Salvager I" if cloaking < 2 else "Covert Ops Cloaking Device II",
                "role": "Salvages wrecks in sites" if cloaking < 2 else "Enables warping while cloaked",
                "required": False,
                "approx_price_isk": 150_000 if cloaking < 2 else 3_500_000,
            },
        ],
        "mid_slots": [
            {
                "module": "Relic Analyzer I",
                "role": "Required to hack Relic sites (Ancient treasure containers)",
                "required": True,
                "approx_price_isk": 55_000,
            },
            {
                "module": "Data Analyzer I",
                "role": "Required to hack Data sites (tech and blueprint caches)",
                "required": True,
                "approx_price_isk": 25_000,
            },
            {
                "module": "1MN Afterburner I",
                "role": "Speed boost — critical for approaching containers quickly in sites",
                "required": True,
                "approx_price_isk": 30_000,
            },
            {
                "module": "Medium Shield Extender I",
                "role": "Buffer tank — more buffer means more time to warp out if caught",
                "required": False,
                "approx_price_isk": 80_000,
            },
        ],
        "low_slots": [
            {
                "module": "Gravity Capacitor Upgrade I",
                "role": "Increases scan strength — makes probes lock signatures faster",
                "required": True,
                "approx_price_isk": 400_000,
            },
            {
                "module": "Inertia Stabilizers I",
                "role": "Faster align time — you warp out quicker if someone tries to catch you",
                "required": False,
                "approx_price_isk": 25_000,
            },
        ],
        "rig_slots": [
            {
                "module": "Small Gravity Capacitor Upgrade I",
                "role": "Largest scan strength bonus available — always fit two of these",
                "required": True,
                "approx_price_isk": 750_000,
            },
            {
                "module": "Small Gravity Capacitor Upgrade I",
                "role": "Second scan strength rig — stack both for maximum probe effectiveness",
                "required": True,
                "approx_price_isk": 750_000,
            },
            {
                "module": "Small Low Friction Nozzle Joints I",
                "role": "Further reduces align time — harder to catch at gates and sites",
                "required": False,
                "approx_price_isk": 300_000,
            },
        ],
        "cargo_essentials": [
            {"item": "Core Scanner Probe I x16", "note": "Always carry spares — probes get consumed", "approx_price_isk": 80_000},
            {"item": "Expanded Cargohold I", "note": "Swap in if you need more loot space on a long run", "approx_price_isk": 5_000},
        ],
        "skill_notes": [],
        "skill_levels_detected": {
            "Astrometrics": astrometrics,
            "Astrometric Rangefinding": astr_rangefinding,
            "Hacking": hacking,
            "Archaeology": archaeology,
            "Cloaking": cloaking,
        },
    }

    # Skill-based advice
    if astrometrics < 3:
        fit["skill_notes"].append(
            f"Train Astrometrics to 3 minimum (you have {astrometrics}). "
            "Each level adds a probe, cuts scan time, boosts strength."
        )
    if hacking < 3:
        fit["skill_notes"].append(
            f"Hacking {hacking}/5 — train to 3 for reliable Data site hacking."
        )
    if archaeology < 3:
        fit["skill_notes"].append(
            f"Archaeology {archaeology}/5 — train to 3 for reliable Relic site hacking. "
            "Relic sites pay far more than Data sites — this skill is priority."
        )
    if astr_rangefinding >= 1:
        fit["skill_notes"].append(
            f"Astrometric Rangefinding {astr_rangefinding}/5 — good. "
            "Each level reduces the max scan deviation, making probes more precise."
        )

    # Total cost estimate
    all_modules = (
        fit["high_slots"] + fit["mid_slots"] +
        fit["low_slots"] + fit["rig_slots"]
    )
    total_required = sum(
        m["approx_price_isk"] for m in all_modules if m.get("required")
    )
    total_optional = sum(
        m["approx_price_isk"] for m in all_modules if not m.get("required")
    )
    total_all = total_required + total_optional

    fit["cost_estimate"] = {
        "required_modules_only": total_required,
        "full_fit_with_optionals": total_all,
        "budget_provided": budget_isk,
        "fits_budget": total_all <= budget_isk,
        "note": (
            f"Full fit costs ~{total_all:,.0f} ISK. "
            f"At your budget of {budget_isk:,.0f} ISK this is "
            f"{'well within budget' if total_all <= budget_isk else 'over budget — skip the optionals'}."
        ),
    }

    return fit
