"""
Market-related MCP tools.

EVE's markets are regional. Most trading happens in The Forge (Jita).
These tools let the agent answer questions like:
  - What does X cost in Jita right now?
  - What's the buy/sell spread for Y?
  - Where is Z cheapest to buy?
  - What are my open market orders?
  - What public contracts list item X (BPCs, fitted ships, etc.)?
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from eve_agent import auth
from eve_agent.esi_client import ESIClient
from eve_agent.sde import get_system, get_type, search_systems, search_types


log = logging.getLogger(__name__)


# Hub region IDs (top trade hubs by volume)
HUB_REGIONS = {
    "Jita":   {"region_id": 10000002, "system_id": 30000142, "name": "The Forge"},
    "Amarr":  {"region_id": 10000043, "system_id": 30002187, "name": "Domain"},
    "Dodixie":{"region_id": 10000032, "system_id": 30002659, "name": "Sinq Laison"},
    "Rens":   {"region_id": 10000030, "system_id": 30002510, "name": "Heimatar"},
    "Hek":    {"region_id": 10000042, "system_id": 30002053, "name": "Metropolis"},
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
    # Prefer exact case-insensitive match
    for m in matches:
        if m["name"].lower() == s.lower():
            return m["type_id"]
    # Otherwise return the first published match
    return matches[0]["type_id"]


def _resolve_region_id(hub_or_region: str) -> Optional[int]:
    s = str(hub_or_region).strip()
    if s.isdigit():
        return int(s)
    # Hub system name?
    if s in HUB_REGIONS:
        return HUB_REGIONS[s]["region_id"]
    # Region name search
    from eve_agent.sde import _conn
    row = _conn().execute(
        "SELECT regionID FROM mapRegions WHERE regionName LIKE ? COLLATE NOCASE LIMIT 1",
        (f"%{s}%",),
    ).fetchone()
    return row[0] if row else None


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
async def get_market_price(
    item: str,
    hub: str = "Jita",
) -> dict:
    """
    Fetch live best-buy and best-sell prices for an item in a market hub.
    Returns highest buy, lowest sell, and the spread.
    """
    type_id = _resolve_type_id(item)
    if not type_id:
        return {"error": f"Could not resolve item '{item}'."}

    if hub not in HUB_REGIONS:
        return {"error": f"Unknown hub '{hub}'. Try one of: {list(HUB_REGIONS)}"}

    hub_info = HUB_REGIONS[hub]
    region_id = hub_info["region_id"]
    system_id = hub_info["system_id"]

    type_info = get_type(type_id)
    item_name = type_info["name"] if type_info else f"Type {type_id}"

    async with ESIClient() as esi:
        # Buy orders
        buy_orders = await esi.get_paginated(
            f"/markets/{region_id}/orders/",
            params={"type_id": type_id, "order_type": "buy"},
            authenticated=False,
        )
        sell_orders = await esi.get_paginated(
            f"/markets/{region_id}/orders/",
            params={"type_id": type_id, "order_type": "sell"},
            authenticated=False,
        )

    # Filter to orders in the hub system
    hub_buys = [o for o in buy_orders if o["system_id"] == system_id]
    hub_sells = [o for o in sell_orders if o["system_id"] == system_id]

    best_buy = max((o["price"] for o in hub_buys), default=None)
    best_sell = min((o["price"] for o in hub_sells), default=None)
    spread = (best_sell - best_buy) if (best_buy and best_sell) else None
    margin_pct = (spread / best_sell * 100) if (spread and best_sell) else None

    return {
        "item": item_name,
        "type_id": type_id,
        "hub": hub,
        "best_buy": best_buy,
        "best_sell": best_sell,
        "spread": spread,
        "margin_pct": round(margin_pct, 2) if margin_pct is not None else None,
        "buy_orders_count": len(hub_buys),
        "sell_orders_count": len(hub_sells),
        "formatted": (
            f"{item_name} in {hub}: "
            f"buy {best_buy:,.2f} / sell {best_sell:,.2f}"
            if best_buy and best_sell
            else f"{item_name} in {hub}: limited orders"
        ),
    }


async def compare_hub_prices(item: str) -> dict:
    """
    Compare best-buy and best-sell prices for an item across all major
    trade hubs. Useful for finding arbitrage or where to buy/sell.
    """
    type_id = _resolve_type_id(item)
    if not type_id:
        return {"error": f"Could not resolve item '{item}'."}

    type_info = get_type(type_id)
    item_name = type_info["name"] if type_info else f"Type {type_id}"

    results = {}
    async with ESIClient() as esi:
        for hub_name, hub_info in HUB_REGIONS.items():
            try:
                buy_orders = await esi.get_paginated(
                    f"/markets/{hub_info['region_id']}/orders/",
                    params={"type_id": type_id, "order_type": "buy"},
                    authenticated=False,
                )
                sell_orders = await esi.get_paginated(
                    f"/markets/{hub_info['region_id']}/orders/",
                    params={"type_id": type_id, "order_type": "sell"},
                    authenticated=False,
                )
                hub_buys = [o for o in buy_orders if o["system_id"] == hub_info["system_id"]]
                hub_sells = [o for o in sell_orders if o["system_id"] == hub_info["system_id"]]
                results[hub_name] = {
                    "best_buy": max((o["price"] for o in hub_buys), default=None),
                    "best_sell": min((o["price"] for o in hub_sells), default=None),
                    "buy_count": len(hub_buys),
                    "sell_count": len(hub_sells),
                }
            except Exception as e:
                log.warning("Failed for hub %s: %s", hub_name, e)
                results[hub_name] = {"error": str(e)}

    # Find best places
    valid_sells = {h: r["best_sell"] for h, r in results.items() if r.get("best_sell")}
    valid_buys = {h: r["best_buy"] for h, r in results.items() if r.get("best_buy")}

    cheapest_sell = min(valid_sells.items(), key=lambda kv: kv[1]) if valid_sells else None
    highest_buy = max(valid_buys.items(), key=lambda kv: kv[1]) if valid_buys else None

    arbitrage = None
    if cheapest_sell and highest_buy and highest_buy[1] > cheapest_sell[1]:
        arbitrage = {
            "buy_at": cheapest_sell[0],
            "buy_price": cheapest_sell[1],
            "sell_at": highest_buy[0],
            "sell_price": highest_buy[1],
            "profit_per_unit": highest_buy[1] - cheapest_sell[1],
        }

    return {
        "item": item_name,
        "type_id": type_id,
        "hubs": results,
        "cheapest_to_buy_from_sell": (
            {"hub": cheapest_sell[0], "price": cheapest_sell[1]}
            if cheapest_sell else None
        ),
        "highest_buy_order": (
            {"hub": highest_buy[0], "price": highest_buy[1]}
            if highest_buy else None
        ),
        "arbitrage_opportunity": arbitrage,
    }


async def get_market_history(
    item: str,
    region: str = "Jita",
    days: int = 30,
) -> dict:
    """
    Get daily market history for an item in a region. Returns averages,
    high/low, and volume for the last N days.
    """
    type_id = _resolve_type_id(item)
    if not type_id:
        return {"error": f"Could not resolve item '{item}'."}

    region_id = _resolve_region_id(region)
    if not region_id:
        return {"error": f"Could not resolve region '{region}'."}

    type_info = get_type(type_id)
    item_name = type_info["name"] if type_info else f"Type {type_id}"

    async with ESIClient() as esi:
        history = await esi.get(
            f"/markets/{region_id}/history/",
            params={"type_id": type_id},
            authenticated=False,
        )

    if not history:
        return {"item": item_name, "history": [], "error": "No history available."}

    # Last N days
    recent = history[-days:]
    avg_price = sum(d["average"] for d in recent) / len(recent)
    avg_volume = sum(d["volume"] for d in recent) / len(recent)
    high = max(d["highest"] for d in recent)
    low = min(d["lowest"] for d in recent)

    # Trend: compare last 7 days to previous 7 days
    trend = None
    if len(recent) >= 14:
        recent_avg = sum(d["average"] for d in recent[-7:]) / 7
        prior_avg = sum(d["average"] for d in recent[-14:-7]) / 7
        change_pct = ((recent_avg - prior_avg) / prior_avg) * 100
        trend = {
            "last_7d_avg": recent_avg,
            "prior_7d_avg": prior_avg,
            "change_pct": round(change_pct, 2),
            "direction": "up" if change_pct > 1 else "down" if change_pct < -1 else "flat",
        }

    return {
        "item": item_name,
        "type_id": type_id,
        "region": region,
        "days_analyzed": len(recent),
        "average_price": round(avg_price, 2),
        "average_daily_volume": round(avg_volume),
        "period_high": high,
        "period_low": low,
        "trend": trend,
        "latest_day": recent[-1] if recent else None,
    }


async def get_my_market_orders() -> dict:
    """List the character's currently open market buy and sell orders."""
    cid = _current_character_id()
    async with ESIClient() as esi:
        orders = await esi.get(
            f"/characters/{cid}/orders/", character_id=cid
        )

    enriched = []
    for o in orders:
        type_info = get_type(o["type_id"])
        sys_info = get_system(o["region_id"])  # not quite — but used as fallback
        enriched.append({
            "order_id": o["order_id"],
            "item": type_info["name"] if type_info else f"Type {o['type_id']}",
            "is_buy_order": o.get("is_buy_order", False),
            "price": o["price"],
            "volume_remain": o["volume_remain"],
            "volume_total": o["volume_total"],
            "issued": o.get("issued"),
            "duration_days": o.get("duration"),
            "location_id": o.get("location_id"),
        })

    buys = [o for o in enriched if o["is_buy_order"]]
    sells = [o for o in enriched if not o["is_buy_order"]]
    total_buy_isk = sum(o["price"] * o["volume_remain"] for o in buys)
    total_sell_value = sum(o["price"] * o["volume_remain"] for o in sells)

    return {
        "open_buy_orders": len(buys),
        "open_sell_orders": len(sells),
        "isk_locked_in_buy_orders": total_buy_isk,
        "total_sell_listing_value": total_sell_value,
        "orders": enriched,
    }


# ---------------------------------------------------------------------------
# Public contracts (BPCs, fitted ships, item exchange, auctions)
# ---------------------------------------------------------------------------

# Common Jita station IDs used to filter "near Jita" contracts
JITA_STATION_IDS = {
    60003760,  # Jita IV - Moon 4 - Caldari Navy Assembly Plant
    60012082,  # Jita IV - Moon 4 - Hyasyoda
}


async def search_contracts(
    item: str,
    region: str = "Jita",
    contract_type: str = "item_exchange",
    max_pages: int = 3,
    max_results: int = 25,
    jita_only: bool = True,
) -> dict:
    """
    Search public contracts in a region for ones containing a specific item.

    Use this for things the regional market doesn't carry: BPCs, fitted ships,
    rigged hulls, asset packages, T2 BPOs, etc.

    Walks public contract pages (cached 30 min by ESI), filters by contract
    type, then concurrently fetches each contract's item list (cached 1 hour)
    to find matches by type_id. First call against a region is slow
    (potentially 30-90s). Subsequent calls within the cache window are fast.

    Args:
        item: item name or type_id to find inside contracts
        region: hub name (Jita/Amarr/...) or region name
        contract_type: 'item_exchange' (fixed price), 'auction', or 'any'
        max_pages: how many pages of public contracts to scan (1000 per page)
        max_results: stop once this many matching contracts are found
        jita_only: if True and region is Jita, only return contracts at
                   Jita IV-4 stations (filters out station containers in space)
    """
    type_id = _resolve_type_id(item)
    if not type_id:
        return {"error": f"Could not resolve item '{item}'."}

    region_id = _resolve_region_id(region)
    if not region_id:
        return {"error": f"Could not resolve region '{region}'."}

    type_info = get_type(type_id)
    item_name = type_info["name"] if type_info else f"Type {type_id}"

    wanted_types: set[str] = set()
    if contract_type == "any":
        wanted_types = {"item_exchange", "auction"}
    elif contract_type in ("item_exchange", "auction", "courier"):
        wanted_types = {contract_type}
    else:
        return {"error": f"Unknown contract_type '{contract_type}'."}

    apply_jita_filter = jita_only and region.lower() == "jita"

    async with ESIClient() as esi:
        # Walk public contract listing pages
        contracts = await esi.get_paginated(
            f"/contracts/public/{region_id}/",
            authenticated=False,
            max_pages=max_pages,
        )

        # Pre-filter: type, has price, and (optionally) Jita station
        candidates = []
        for c in contracts:
            if c.get("type") not in wanted_types:
                continue
            if not c.get("price") or c["price"] <= 0:
                continue
            if apply_jita_filter and c.get("end_location_id") not in JITA_STATION_IDS:
                continue
            candidates.append(c)

        if not candidates:
            return {
                "item": item_name,
                "type_id": type_id,
                "region": region,
                "contracts_scanned": len(contracts),
                "candidates_after_filter": 0,
                "matches": [],
                "note": "No matching public contracts in scanned pages.",
            }

        # Concurrently fetch items for each candidate, scanning for our type_id
        sem = asyncio.Semaphore(20)
        matches: list[dict] = []
        stop_event = asyncio.Event()

        async def check_contract(c: dict) -> None:
            if stop_event.is_set():
                return
            async with sem:
                if stop_event.is_set():
                    return
                try:
                    items = await esi.get(
                        f"/contracts/public/items/{c['contract_id']}/",
                        authenticated=False,
                    )
                except Exception as e:
                    log.debug("Items fetch failed for contract %s: %s",
                              c.get("contract_id"), e)
                    return

            if not isinstance(items, list):
                return

            # Find matching included item (skip "is_included=False" — those
            # are items the buyer must supply, not items being sold)
            matched_qty = sum(
                it.get("quantity", 0) for it in items
                if it.get("type_id") == type_id and it.get("is_included", True)
            )
            if matched_qty <= 0:
                return

            # BPC details if present
            first_match = next(
                (it for it in items if it.get("type_id") == type_id), {}
            )
            is_bpc = first_match.get("is_blueprint_copy", False)

            matches.append({
                "contract_id": c["contract_id"],
                "price": c["price"],
                "matched_quantity": matched_qty,
                "items_in_contract": len(items),
                "issuer_id": c.get("issuer_id"),
                "end_location_id": c.get("end_location_id"),
                "date_expired": c.get("date_expired"),
                "title": c.get("title", ""),
                "type": c.get("type"),
                "is_blueprint_copy": is_bpc,
                "runs": first_match.get("runs") if is_bpc else None,
                "material_efficiency": first_match.get("material_efficiency") if is_bpc else None,
                "time_efficiency": first_match.get("time_efficiency") if is_bpc else None,
            })
            if len(matches) >= max_results:
                stop_event.set()

        await asyncio.gather(*(check_contract(c) for c in candidates))

    matches.sort(key=lambda m: m["price"])
    cheapest = matches[0] if matches else None
    prices = [m["price"] for m in matches]
    median_price = sorted(prices)[len(prices) // 2] if prices else None

    return {
        "item": item_name,
        "type_id": type_id,
        "region": region,
        "contract_type": contract_type,
        "contracts_scanned": len(contracts),
        "candidates_after_filter": len(candidates),
        "matches_found": len(matches),
        "cheapest_price": cheapest["price"] if cheapest else None,
        "median_price": median_price,
        "matches": matches[:max_results],
    }