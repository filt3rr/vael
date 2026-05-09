"""
Industry-related MCP tools.

Manufacturing, blueprints, jobs.
"""

from __future__ import annotations

import logging
from typing import Optional

from eve_agent import auth
from eve_agent.esi_client import ESIClient
from eve_agent.sde import _conn, get_system, get_type, search_types


log = logging.getLogger(__name__)


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


# ---------------------------------------------------------------------------
# Blueprint material requirements (from the SDE)
# ---------------------------------------------------------------------------
def _get_blueprint_for_product(product_type_id: int) -> Optional[dict]:
    """Find the blueprint that manufactures a given product."""
    row = _conn().execute(
        """
        SELECT typeID AS blueprint_type_id, productTypeID AS product_type_id
        FROM industryActivityProducts
        WHERE productTypeID = ? AND activityID = 1
        LIMIT 1
        """,
        (product_type_id,),
    ).fetchone()
    return dict(row) if row else None


def _get_manufacturing_materials(blueprint_type_id: int) -> list[dict]:
    """Return the bill of materials for manufacturing from a blueprint."""
    rows = _conn().execute(
        """
        SELECT m.materialTypeID AS type_id,
               t.typeName       AS name,
               m.quantity       AS quantity
        FROM industryActivityMaterials m
        LEFT JOIN invTypes t ON t.typeID = m.materialTypeID
        WHERE m.typeID = ? AND m.activityID = 1
        ORDER BY m.quantity DESC
        """,
        (blueprint_type_id,),
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
async def get_active_industry_jobs() -> dict:
    """List the character's active industry jobs (manufacturing, research, etc)."""
    cid = _current_character_id()
    async with ESIClient() as esi:
        jobs = await esi.get(
            f"/characters/{cid}/industry/jobs/", character_id=cid
        )

    activity_names = {
        1: "Manufacturing", 3: "Time Efficiency Research",
        4: "Material Efficiency Research", 5: "Copying",
        7: "Reverse Engineering", 8: "Invention", 11: "Reactions",
    }

    enriched = []
    for j in jobs:
        product = get_type(j.get("product_type_id")) if j.get("product_type_id") else None
        blueprint = get_type(j["blueprint_type_id"])
        enriched.append({
            "job_id": j["job_id"],
            "activity": activity_names.get(j["activity_id"], f"Activity {j['activity_id']}"),
            "blueprint": blueprint["name"] if blueprint else None,
            "product": product["name"] if product else None,
            "runs": j["runs"],
            "status": j.get("status"),
            "start_date": j.get("start_date"),
            "end_date": j.get("end_date"),
            "duration_seconds": j.get("duration"),
            "cost": j.get("cost"),
        })

    return {"count": len(enriched), "jobs": enriched}


async def get_blueprint_info(item: str) -> dict:
    """
    For a given product name (e.g. 'Rifter'), find its blueprint and
    return material requirements and manufacturing time.
    """
    product_type_id = _resolve_type_id(item)
    if not product_type_id:
        return {"error": f"Could not resolve item '{item}'."}

    product = get_type(product_type_id)
    bp_link = _get_blueprint_for_product(product_type_id)
    if not bp_link:
        return {
            "error": f"No manufacturing blueprint produces '{product['name']}'.",
            "product": product["name"],
        }

    bp_type = get_type(bp_link["blueprint_type_id"])
    materials = _get_manufacturing_materials(bp_link["blueprint_type_id"])

    # Manufacturing time
    time_row = _conn().execute(
        "SELECT time FROM industryActivity WHERE typeID = ? AND activityID = 1",
        (bp_link["blueprint_type_id"],),
    ).fetchone()
    base_time = time_row[0] if time_row else None

    return {
        "product": product["name"],
        "product_type_id": product_type_id,
        "blueprint": bp_type["name"] if bp_type else None,
        "blueprint_type_id": bp_link["blueprint_type_id"],
        "base_manufacturing_time_seconds": base_time,
        "base_manufacturing_time_formatted": _format_seconds(base_time) if base_time else None,
        "materials_per_run": materials,
        "materials_count": len(materials),
    }


async def calculate_manufacturing_cost(
    item: str,
    runs: int = 1,
    me_level: int = 0,
    hub: str = "Jita",
) -> dict:
    """
    Calculate the manufacturing cost of an item by pulling LIVE Jita prices
    for each material. Useful for "is it profitable to build this?"

    me_level (0-10) reduces material requirements. ME 10 = ~10% reduction.
    """
    product_type_id = _resolve_type_id(item)
    if not product_type_id:
        return {"error": f"Could not resolve item '{item}'."}

    bp_link = _get_blueprint_for_product(product_type_id)
    if not bp_link:
        return {"error": f"No blueprint manufactures {item}."}

    materials = _get_manufacturing_materials(bp_link["blueprint_type_id"])
    if not materials:
        return {"error": "Blueprint has no material requirements."}

    # ME formula: actual = ceil(base * runs * (1 - ME/100))
    import math
    me_multiplier = 1 - (me_level / 100)

    # Hub region (default Jita)
    from eve_agent.tools.market import HUB_REGIONS
    if hub not in HUB_REGIONS:
        hub = "Jita"
    region_id = HUB_REGIONS[hub]["region_id"]
    system_id = HUB_REGIONS[hub]["system_id"]

    # Look up live sell prices for each material
    breakdown = []
    total_cost = 0.0

    async with ESIClient() as esi:
        for mat in materials:
            needed = max(1, math.ceil(mat["quantity"] * runs * me_multiplier))
            try:
                sells = await esi.get_paginated(
                    f"/markets/{region_id}/orders/",
                    params={"type_id": mat["type_id"], "order_type": "sell"},
                    authenticated=False,
                )
                hub_sells = [o["price"] for o in sells if o["system_id"] == system_id]
                price = min(hub_sells) if hub_sells else None
            except Exception as e:
                price = None
                log.warning("Price fetch failed for %s: %s", mat["name"], e)

            line_cost = price * needed if price else None
            if line_cost:
                total_cost += line_cost

            breakdown.append({
                "material": mat["name"],
                "quantity_needed": needed,
                "unit_price": price,
                "line_cost": line_cost,
            })

        # Get sell price of the product for profit calculation
        product_sells = await esi.get_paginated(
            f"/markets/{region_id}/orders/",
            params={"type_id": product_type_id, "order_type": "sell"},
            authenticated=False,
        )
        product_hub_sells = [o["price"] for o in product_sells if o["system_id"] == system_id]
        product_sell_price = min(product_hub_sells) if product_hub_sells else None

    revenue = product_sell_price * runs if product_sell_price else None
    profit = (revenue - total_cost) if revenue else None
    margin_pct = (profit / revenue * 100) if revenue and profit else None

    product = get_type(product_type_id)
    return {
        "product": product["name"],
        "runs": runs,
        "me_level": me_level,
        "hub": hub,
        "material_cost_total": round(total_cost, 2),
        "product_sell_price": product_sell_price,
        "revenue_at_sell_price": revenue,
        "estimated_profit": round(profit, 2) if profit is not None else None,
        "profit_margin_pct": round(margin_pct, 2) if margin_pct is not None else None,
        "profitable": profit > 0 if profit is not None else None,
        "materials_breakdown": breakdown,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _format_seconds(seconds: int) -> str:
    if seconds is None:
        return "?"
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    mins = rem // 60
    parts = []
    if days: parts.append(f"{days}d")
    if hours: parts.append(f"{hours}h")
    if mins: parts.append(f"{mins}m")
    return " ".join(parts) if parts else "<1m"