"""
Character-related MCP tools.

Each function here is exposed to Claude as a callable tool. They are all
async, return JSON-serializable dicts, and convert raw ESI IDs into
human-readable names via the SDE.

Tools defined here:
    get_character_summary()        - high-level snapshot of who you are
    get_wallet_balance()           - current ISK
    get_skill_overview()           - total SP, training queue, alpha/omega
    get_current_location()         - system, station/structure, ship
    get_asset_summary()            - top items by quantity & by value
    get_assets_by_location()       - assets bucketed by station/system
    list_recent_wallet_journal()   - last N wallet transactions
"""

from __future__ import annotations

import logging
from typing import Optional

from eve_agent import auth
from eve_agent.esi_client import ESIClient
from eve_agent.sde import (
    get_station,
    get_system,
    get_type,
)


log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper: resolve the calling character id (we only support one for now)
# ---------------------------------------------------------------------------
def _current_character_id() -> int:
    chars = auth.list_characters()
    if not chars:
        raise RuntimeError(
            "No authenticated character. Run `python -m eve_agent.auth`."
        )
    return chars[0].character_id


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
async def get_character_summary() -> dict:
    """
    Return a high-level snapshot of the authenticated character:
    name, corp, alliance, security status, ISK balance, location, current ship.
    """
    cid = _current_character_id()

    async with ESIClient() as esi:
        info = await esi.get(f"/characters/{cid}/", authenticated=False)
        wallet = await esi.get(f"/characters/{cid}/wallet/", character_id=cid)
        location = await esi.get(f"/characters/{cid}/location/", character_id=cid)
        ship = await esi.get(f"/characters/{cid}/ship/", character_id=cid)
        online = await esi.get(f"/characters/{cid}/online/", character_id=cid)

        # Resolve corp/alliance names
        corp = await esi.get(
            f"/corporations/{info['corporation_id']}/",
            authenticated=False,
        )
        alliance_name = None
        if "alliance_id" in info:
            alliance = await esi.get(
                f"/alliances/{info['alliance_id']}/",
                authenticated=False,
            )
            alliance_name = alliance.get("name")

    # Resolve location names
    system = get_system(location["solar_system_id"])
    location_text = system["name"] if system else f"System {location['solar_system_id']}"

    if "station_id" in location:
        station = get_station(location["station_id"])
        if station:
            location_text = f"{station['name']} ({system['name']})"
    elif "structure_id" in location:
        # Player structures aren't in the SDE — try ESI (may need scope)
        location_text = f"Structure {location['structure_id']} (in {system['name']})"

    ship_type = get_type(ship["ship_type_id"])
    ship_name = ship_type["name"] if ship_type else f"Type {ship['ship_type_id']}"

    return {
        "character_name": info["name"],
        "character_id": cid,
        "security_status": round(info.get("security_status", 0.0), 3),
        "birthday": info.get("birthday"),
        "corporation": corp.get("name"),
        "corporation_ticker": corp.get("ticker"),
        "alliance": alliance_name,
        "isk_balance": float(wallet),
        "location": location_text,
        "system_security": round(system["security"], 2) if system else None,
        "current_ship": ship_name,
        "current_ship_name": ship.get("ship_name"),
        "online": online.get("online", False),
        "last_login": online.get("last_login"),
    }


async def get_wallet_balance() -> dict:
    """Return the character's ISK wallet balance."""
    cid = _current_character_id()
    async with ESIClient() as esi:
        balance = await esi.get(
            f"/characters/{cid}/wallet/", character_id=cid
        )
    return {"isk_balance": float(balance), "formatted": f"{balance:,.2f} ISK"}


async def get_skill_overview() -> dict:
    """
    Return total SP, current training, queue length, and alpha/omega status.
    """
    cid = _current_character_id()

    async with ESIClient() as esi:
        skills = await esi.get(
            f"/characters/{cid}/skills/", character_id=cid
        )
        queue = await esi.get(
            f"/characters/{cid}/skillqueue/", character_id=cid
        )

    # Resolve currently training skill (first item with training_start_sp)
    currently_training = None
    if queue:
        head = queue[0]
        skill = get_type(head["skill_id"])
        currently_training = {
            "skill_name": skill["name"] if skill else f"Skill {head['skill_id']}",
            "to_level": head.get("finished_level"),
            "finish_date": head.get("finish_date"),
        }

    return {
        "total_sp": skills.get("total_sp"),
        "unallocated_sp": skills.get("unallocated_sp", 0),
        "skills_count": len(skills.get("skills", [])),
        "queue_length": len(queue),
        "currently_training": currently_training,
    }


async def get_current_location() -> dict:
    """Return where the character currently is and what they're flying."""
    cid = _current_character_id()

    async with ESIClient() as esi:
        location = await esi.get(f"/characters/{cid}/location/", character_id=cid)
        ship = await esi.get(f"/characters/{cid}/ship/", character_id=cid)

    system = get_system(location["solar_system_id"])
    ship_type = get_type(ship["ship_type_id"])

    result = {
        "system_id": location["solar_system_id"],
        "system_name": system["name"] if system else None,
        "system_security": round(system["security"], 2) if system else None,
        "region": system["region_name"] if system else None,
        "constellation": system["constellation_name"] if system else None,
        "docked": "station_id" in location or "structure_id" in location,
        "ship_type": ship_type["name"] if ship_type else None,
        "ship_name": ship.get("ship_name"),
    }

    if "station_id" in location:
        station = get_station(location["station_id"])
        result["station"] = station["name"] if station else f"Station {location['station_id']}"
    elif "structure_id" in location:
        result["structure_id"] = location["structure_id"]

    return result


async def get_asset_summary(top_n: int = 10) -> dict:
    """
    Return summary of all assets: total count, top items by quantity, top by
    estimated bulk value. ISK valuation requires market data we don't yet
    fetch here, so we return a count-based summary for now.
    """
    cid = _current_character_id()

    async with ESIClient() as esi:
        assets = await esi.get_paginated(
            f"/characters/{cid}/assets/", character_id=cid
        )

    # Aggregate by type_id
    by_type: dict[int, int] = {}
    for asset in assets:
        type_id = asset["type_id"]
        qty = asset.get("quantity", 1)
        by_type[type_id] = by_type.get(type_id, 0) + qty

    # Resolve names for top N by quantity
    top_by_qty = sorted(by_type.items(), key=lambda kv: -kv[1])[:top_n]
    top_items = []
    for type_id, qty in top_by_qty:
        t = get_type(type_id)
        top_items.append({
            "type_id": type_id,
            "name": t["name"] if t else f"Type {type_id}",
            "category": t["category_name"] if t else None,
            "quantity": qty,
        })

    # Distribution by category
    by_category: dict[str, int] = {}
    for type_id, qty in by_type.items():
        t = get_type(type_id)
        cat = t["category_name"] if t else "Unknown"
        by_category[cat] = by_category.get(cat, 0) + qty

    return {
        "total_asset_records": len(assets),
        "unique_item_types": len(by_type),
        "top_items_by_quantity": top_items,
        "category_distribution": dict(
            sorted(by_category.items(), key=lambda kv: -kv[1])[:10]
        ),
    }


async def get_assets_by_location(top_n: int = 10) -> dict:
    """
    Group all assets by their root location (NPC station, player structure, or
    solar system). Resolves NPC station and system names via the SDE. Player
    structures (citadels) lack the universe.read_structures scope so they are
    reported by ID only. Items inside containers or fitted to ships are walked
    up to their root location.

    Returns the top N locations by asset record count, with a per-location
    breakdown of unique types, ship count, and dominant categories.
    """
    cid = _current_character_id()

    async with ESIClient() as esi:
        assets = await esi.get_paginated(
            f"/characters/{cid}/assets/", character_id=cid
        )

    # Build item_id -> asset map so we can walk container chains up to root.
    by_item_id = {a["item_id"]: a for a in assets if "item_id" in a}

    def root_location(asset: dict) -> tuple[int, str]:
        """Walk up containers/ships until we hit a non-item location."""
        cur = asset
        seen: set[int] = set()
        for _ in range(16):  # guard against cycles
            loc_id = cur.get("location_id")
            loc_type = cur.get("location_type")
            if loc_id is None:
                return (0, "unknown")
            if loc_type != "item" or loc_id not in by_item_id:
                return (loc_id, loc_type or "unknown")
            if loc_id in seen:
                return (loc_id, "unknown")
            seen.add(loc_id)
            cur = by_item_id[loc_id]
        return (cur.get("location_id", 0), cur.get("location_type", "unknown"))

    # Bucket assets by root location.
    buckets: dict[int, dict] = {}
    for asset in assets:
        loc_id, loc_type = root_location(asset)
        b = buckets.setdefault(loc_id, {
            "location_id": loc_id,
            "location_type": loc_type,
            "records": 0,
            "type_ids": set(),
            "ship_count": 0,
            "ships": [],
            "categories": {},
        })
        b["records"] += 1
        b["type_ids"].add(asset["type_id"])
        t = get_type(asset["type_id"])
        cat = t["category_name"] if t else "Unknown"
        b["categories"][cat] = b["categories"].get(cat, 0) + asset.get("quantity", 1)
        if cat == "Ship":
            b["ship_count"] += 1
            b["ships"].append(t["name"] if t else f"Type {asset['type_id']}")

    # Resolve location names. NPC station IDs are < 100,000,000.
    # Player structure IDs are >= 1,000,000,000,000 (typical citadel range).
    locations = []
    for loc_id, b in buckets.items():
        name = None
        system_name = None
        security = None
        region_name = None

        if b["location_type"] == "station" or (loc_id and loc_id < 100_000_000):
            station = get_station(loc_id)
            if station:
                name = station["name"]
                system_name = station["system_name"]
                region_name = station["region_name"]
                sys = get_system(station["system_id"])
                if sys:
                    security = round(sys["security"], 2)
        elif b["location_type"] == "solar_system":
            sys = get_system(loc_id)
            if sys:
                name = f"{sys['name']} (in space)"
                system_name = sys["name"]
                security = round(sys["security"], 2)
                region_name = sys["region_name"]
        else:
            # Player structure or unknown — no scope to resolve, just label it.
            name = f"Player Structure {loc_id}" if loc_id else "Unknown location"

        top_cats = dict(
            sorted(b["categories"].items(), key=lambda kv: -kv[1])[:5]
        )
        locations.append({
            "location_id": loc_id,
            "location_type": b["location_type"],
            "name": name or f"Location {loc_id}",
            "system": system_name,
            "security": security,
            "region": region_name,
            "asset_records": b["records"],
            "unique_types": len(b["type_ids"]),
            "ship_count": b["ship_count"],
            "ships": sorted(b["ships"]),
            "top_categories_by_qty": top_cats,
        })

    locations.sort(key=lambda x: -x["asset_records"])

    return {
        "total_asset_records": len(assets),
        "total_locations": len(locations),
        "locations": locations[:top_n],
    }


async def list_assets_at_location(location_id: int, category: Optional[str] = None) -> dict:
    """
    List every item the capsuleer owns at a specific root location, with name,
    quantity, and category. Walks container/ship chains to attribute nested items
    to the parent station/system. Optional category filter (e.g. "Ship",
    "Planetary Commodities", "Module") narrows the listing.

    Use this after get_assets_by_location() to drill into a specific hub and
    see exactly what is sitting there.
    """
    cid = _current_character_id()

    async with ESIClient() as esi:
        assets = await esi.get_paginated(
            f"/characters/{cid}/assets/", character_id=cid
        )

    by_item_id = {a["item_id"]: a for a in assets if "item_id" in a}

    def root_location(asset: dict) -> int:
        cur = asset
        seen: set[int] = set()
        for _ in range(16):
            loc_id = cur.get("location_id")
            loc_type = cur.get("location_type")
            if loc_id is None:
                return 0
            if loc_type != "item" or loc_id not in by_item_id:
                return loc_id
            if loc_id in seen:
                return loc_id
            seen.add(loc_id)
            cur = by_item_id[loc_id]
        return cur.get("location_id", 0)

    # Aggregate by type at this location.
    by_type: dict[int, int] = {}
    for asset in assets:
        if root_location(asset) != location_id:
            continue
        tid = asset["type_id"]
        by_type[tid] = by_type.get(tid, 0) + asset.get("quantity", 1)

    items = []
    for tid, qty in by_type.items():
        t = get_type(tid)
        name = t["name"] if t else f"Type {tid}"
        cat = t["category_name"] if t else "Unknown"
        if category and cat.lower() != category.lower():
            continue
        items.append({
            "type_id": tid,
            "name": name,
            "category": cat,
            "quantity": qty,
        })

    items.sort(key=lambda x: (-x["quantity"], x["name"]))

    return {
        "location_id": location_id,
        "filter_category": category,
        "item_count": len(items),
        "items": items,
    }


async def list_recent_wallet_journal(limit: int = 20) -> dict:
    """List the most recent wallet journal entries (transactions, taxes, etc)."""
    cid = _current_character_id()

    async with ESIClient() as esi:
        journal = await esi.get(
            f"/characters/{cid}/wallet/journal/", character_id=cid
        )

    entries = []
    for e in journal[:limit]:
        entries.append({
            "date": e.get("date"),
            "type": e.get("ref_type"),
            "amount": e.get("amount"),
            "balance_after": e.get("balance"),
            "description": e.get("description"),
        })

    return {
        "count": len(entries),
        "entries": entries,
    }


# ---------------------------------------------------------------------------
# Implants & Jump Clones
# ---------------------------------------------------------------------------
async def get_active_implants() -> dict:
    """Return the implants currently plugged into the active clone."""
    cid = _current_character_id()

    async with ESIClient() as esi:
        implant_ids = await esi.get(
            f"/characters/{cid}/implants/", character_id=cid
        )

    implants = []
    for tid in implant_ids:
        t = get_type(tid)
        implants.append({
            "type_id": tid,
            "name": t["name"] if t else f"Unknown ({tid})",
            "group_name": t.get("group_name", "") if t else "",
        })

    return {
        "count": len(implants),
        "implants": implants,
    }


async def get_jump_clones() -> dict:
    """Return jump clones with their locations and installed implants."""
    cid = _current_character_id()

    async with ESIClient() as esi:
        data = await esi.get(
            f"/characters/{cid}/clones/", character_id=cid
        )

    # Home location
    home_loc = data.get("home_location", {})
    home_location_id = home_loc.get("location_id")
    home_name = None
    if home_location_id and home_loc.get("location_type") == "station":
        st = get_station(home_location_id)
        home_name = st["name"] if st else None

    # Jump clones
    clones = []
    for jc in data.get("jump_clones", []):
        loc_id = jc.get("location_id")
        loc_name = jc.get("name") or None
        if not loc_name and jc.get("location_type") == "station":
            st = get_station(loc_id)
            loc_name = st["name"] if st else None

        implants = []
        for tid in jc.get("implants", []):
            t = get_type(tid)
            implants.append({
                "type_id": tid,
                "name": t["name"] if t else f"Unknown ({tid})",
            })

        clones.append({
            "jump_clone_id": jc.get("jump_clone_id"),
            "name": jc.get("name"),
            "location_id": loc_id,
            "location_name": loc_name,
            "location_type": jc.get("location_type"),
            "implants": implants,
        })

    return {
        "home_location": {
            "location_id": home_location_id,
            "location_name": home_name,
            "location_type": home_loc.get("location_type"),
        },
        "last_clone_jump_date": data.get("last_clone_jump_date"),
        "jump_clones_count": len(clones),
        "jump_clones": clones,
    }