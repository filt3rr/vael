# Tools Reference

Complete reference for all 56 MCP tools exposed by the EVE Agent server.

---

## Character Tools

### `get_character_summary()`
Full snapshot of the authenticated character.

**Returns:** name, corp, alliance, security status, ISK balance, current location, current ship, online status, last login

---

### `get_wallet_balance()`
Current ISK wallet balance.

**Returns:** `isk_balance` (float), `formatted` (string with commas)

---

### `get_skill_overview()`
High-level skill summary.

**Returns:** `total_sp`, `unallocated_sp`, `skills_count`, `queue_length`, `currently_training` (with finish date)

---

### `get_current_location()`
Where the character is right now.

**Returns:** `system_name`, `system_security`, `region`, `constellation`, `docked` (bool), `ship_type`, `ship_name`, `station` (if docked)

---

### `get_asset_summary(top_n=10)`
Summary of all character assets.

**Parameters:**
- `top_n` — how many top items to return (default 10)

**Returns:** `total_asset_records`, `unique_item_types`, `top_items_by_quantity` (with names), `category_distribution`

---

### `list_recent_wallet_journal(limit=20)`
Recent wallet journal entries.

**Parameters:**
- `limit` — max entries to return (default 20)

**Returns:** list of entries with `date`, `type`, `amount`, `balance_after`, `description`

---

### `get_assets_by_location(top_n=10)`
Map of where the capsuleer's stuff is: top locations bucketed by station/system.

**Parameters:**
- `top_n` — how many top locations to return (default 10)

**Returns:** `total_locations`, top locations with item counts, ship counts, and category mix

---

### `list_assets_at_location(location_id, category="")`
List every item at a specific location (station/system).

**Parameters:**
- `location_id` — numeric location ID (from `get_assets_by_location`)
- `category` — optional category filter (e.g. "Ship", "Planetary Commodities")

**Returns:** `count`, list of items with name, quantity, and category

---

### `get_active_implants()`
Implants plugged into the capsuleer's active clone.

**Returns:** `count`, list of implants with names and groups

---

### `get_jump_clones()`
Jump clones: locations, installed implants, and last clone-jump timestamp.

**Returns:** `count`, list of clones with location, implants, and cooldown info

---

## Fittings Tools

### `get_saved_fittings()`
Fittings saved in-game via Alt+F → Save Fitting.

**Returns:** list of named fittings with ship type and modules organized by slot (High/Mid/Low/Rigs)

**Note:** Requires `esi-fittings.read_fittings.v1` scope

---

### `get_active_ship_equipment()`
Modules currently fitted to the active ship, read from asset flags.

**Returns:** ship name, modules by slot type, cargo preview

**Note:** Shows items with fitted location flags. May be empty if ship was recently changed — try `get_saved_fittings()` as fallback.

---

### `recommend_exploration_fit(budget_isk=50000000)`
Recommended Heron exploration fit calibrated to current skill levels.

**Parameters:**
- `budget_isk` — your budget (default 50M ISK)

**Returns:** full fit with module names, roles explained, skill notes, and cost estimate

---

## Market Tools

### `get_market_price(item, hub="Jita")`
Live best buy and sell prices in a trade hub.

**Parameters:**
- `item` — item name or type ID
- `hub` — one of: `Jita`, `Amarr`, `Dodixie`, `Rens`, `Hek`

**Returns:** `best_buy`, `best_sell`, `spread`, `margin_pct`, order counts

---

### `compare_hub_prices(item)`
Compare prices across all 5 major trade hubs.

**Parameters:**
- `item` — item name or type ID

**Returns:** prices at all hubs, `cheapest_to_buy_from_sell`, `highest_buy_order`, `arbitrage_opportunity` (if profitable)

---

### `get_market_history(item, region="Jita", days=30)`
Daily price history.

**Parameters:**
- `item` — item name or type ID
- `region` — region name or hub name (default Jita = The Forge)
- `days` — how many days of history (default 30)

**Returns:** `average_price`, `average_daily_volume`, `period_high`, `period_low`, 7-day `trend` (up/flat/down)

---

### `get_my_market_orders()`
All currently open buy and sell orders.

**Returns:** order count by type, `isk_locked_in_buy_orders`, `total_sell_listing_value`, full order list with item names

---

### `search_contracts(item, region="Jita", contract_type="item_exchange", max_pages=3, max_results=25, jita_only=True)`
Search public contracts for an item (BPCs, fitted ships, T2 BPOs, item-exchange packages).

**Parameters:**
- `item` — item name to search for
- `region` — region/hub name (default Jita)
- `contract_type` — type filter: `item_exchange`, `auction`, `courier` (default item_exchange)
- `max_pages` — pages to scan (default 3)
- `max_results` — max results to return (default 25)
- `jita_only` — restrict to Jita 4-4 (default true)

**Returns:** `total_found`, list of matching contracts with price, items, location

**Note:** First call per region is slow (30-90s); results are cached after.

---

## Industry Tools

### `get_active_industry_jobs()`
All active industry jobs with human-readable names.

**Returns:** job count, list with activity type, product, runs, status, start/end dates, cost

---

### `get_blueprint_info(item)`
Bill of materials for manufacturing an item.

**Parameters:**
- `item` — product name (e.g. "Rifter") or type ID

**Returns:** blueprint name, materials per run (with names and quantities), base manufacturing time

---

### `calculate_manufacturing_cost(item, runs=1, me_level=0, hub="Jita")`
Full manufacturing P&L with live market prices.

**Parameters:**
- `item` — product name
- `runs` — number of production runs (default 1)
- `me_level` — blueprint material efficiency 0-10 (default 0)
- `hub` — trade hub for material prices (default Jita)

**Returns:** `material_cost_total`, `product_sell_price`, `revenue_at_sell_price`, `estimated_profit`, `profit_margin_pct`, `profitable` (bool), full `materials_breakdown`

---

### `list_owned_blueprints(filter_name=None, bpo_only=False, bpc_only=False)`
List blueprints owned by the capsuleer with runs, ME, TE, quantity, and location.

**Parameters:**
- `filter_name` — optional name substring filter
- `bpo_only` — show only originals (default false)
- `bpc_only` — show only copies (default false)

**Returns:** `total`, list of blueprints with name, type (BPO/BPC), runs, ME, TE, location

---

## Skills Tools

### `calculate_training_time(skill, target_level, sp_per_minute=30.0)`
How long to train a skill from current level to target.

**Parameters:**
- `skill` — skill name or type ID
- `target_level` — 1-5
- `sp_per_minute` — your training rate (default 30, typical for new char with remap)

**Returns:** `current_level`, `sp_to_train`, estimated time in days/hours/minutes

---

### `can_i_fly(ship)`
Check all skill prerequisites for a ship.

**Parameters:**
- `ship` — ship name (e.g. "Rifter", "Drake", "Caracal")

**Returns:** `can_fly` (bool), `skills_missing_or_too_low` (with current vs required levels), `summary`

---

### `get_skill_queue()`
Full training queue with resolved skill names.

**Returns:** `queue_length`, `queue_total_days`, full queue list with skill names, target levels, and finish dates

---

### `suggest_next_skills(top_n=5)`
High-value foundational skills worth training.

**Parameters:**
- `top_n` — how many suggestions (default 5)

**Returns:** prioritized list with skill name, current level, suggested level, and rationale

---

## Intel Tools

### `get_system_danger(system)`
Danger rating for a solar system based on zKillboard 7-day kill data.

**Parameters:**
- `system` — system name or ID

**Returns:** `danger_rating` (1-10), `kills_last_7d`, `total_isk_destroyed`, `most_killed_ships`, `recommendation`

---

### `get_character_intel(character_name)`
Public dossier on any EVE character.

**Parameters:**
- `character_name` — exact character name

**Returns:** corp, alliance, age in days, security status, killboard stats (kills/losses/ISK), recent kills and losses, zKillboard profile URL

---

### `get_recent_kills_in_system(system, limit=10)`
Most recent kills in a system from zKillboard.

**Parameters:**
- `system` — system name
- `limit` — max kills to return (default 10)

**Returns:** list with ship lost, value, time, attacker count, solo kill flag

---

### `should_i_undock(ship_value_isk=0)`
Risk assessment for undocking in current location.

**Parameters:**
- `ship_value_isk` — your ship's estimated value (optional, for risk vs value analysis)

**Returns:** `danger_rating`, `kills_last_7d`, `recommendation`, `ship_risk` (if value provided)

---

### `get_regional_kill_activity(region="The Forge", top_n=5)`
Kill activity heat map for a region.

**Parameters:**
- `region` — region name (default The Forge)
- `top_n` — how many systems/ships to show (default 5)

**Returns:** total kills/ISK last 7 days, `most_dangerous_systems`, `most_killed_ships`

---

## P&L Engine Tools

### `get_pnl_summary(days=7)`
Overall P&L for the last N days broken down by activity.

**Parameters:**
- `days` — lookback period (default 7)

**Returns:** `total_income`, `total_expenses`, `net_pnl`, `income_breakdown` by activity type, `verdict`

---

### `get_isk_velocity()`
ISK growth rate from wallet snapshots.

**Returns:** `per_hour`, `per_day`, `per_week`, `per_month_projected`, `trend`, milestone projections

---

### `analyze_trading_performance(days=14)`
Which items are winning vs losing in your trading portfolio.

**Parameters:**
- `days` — lookback period (default 14)

**Returns:** items traded, `top_winners`, `loss_items`, estimated P&L per item

---

### `get_activity_breakdown(days=7)`
What activity is generating your ISK.

**Parameters:**
- `days` — lookback period (default 7)

**Returns:** `primary_income_source`, percentage breakdown, Vael's assessment of the pattern

---

### `project_isk_growth(target_isk, scenario="current")`
How long to reach an ISK target at current velocity.

**Parameters:**
- `target_isk` — target ISK amount
- `scenario` — `"current"`, `"optimistic"` (2x rate), or `"conservative"` (0.5x rate)

**Returns:** `days_to_target`, `estimated_arrival`, `weeks_to_target`

---

## Memory Tools

### `read_pilot_memory(category=None)`
Read Vael's persistent cross-session memory.

**Parameters:**
- `category` — optional filter: `goals`, `milestones`, `mistakes`, `market_notes`, `skill_plan`, `isk_log`, `session_notes`

---

### `write_pilot_memory(category, key, value)`
Write or update a memory entry.

**Parameters:**
- `category` — one of the valid categories above
- `key` — entry name (e.g. "primary_goal", "tritanium_note")
- `value` — string value to store

---

### `append_pilot_memory(category, entry)`
Append a timestamped entry to a running log.

**Parameters:**
- `category` — memory category
- `entry` — text to log (timestamped automatically)

---

### `log_isk_snapshot(note="")`
Record current ISK balance as a snapshot for velocity tracking.

**Parameters:**
- `note` — optional context note

---

### `get_isk_history(last_n=20)`
Recent ISK snapshots with trend analysis.

**Parameters:**
- `last_n` — how many snapshots to return (default 20)

---

## Watch Tools

### `add_watch(watch_type, label, params)`
Add a proactive alert condition.

**Parameters:**
- `watch_type` — one of: `price_below`, `price_above`, `danger_spike`, `isk_below`, `isk_above`, `skill_soon`, `route_danger`
- `label` — unique name for this watch
- `params` — dict with type-specific parameters:

```python
# price_below / price_above
{"item": "Tritanium", "threshold": 3.50, "hub": "Jita"}

# danger_spike
{"system": "Uedama", "threshold": 8}

# isk_below / isk_above
{"threshold": 100_000_000}

# skill_soon
{"hours_before": 24}

# route_danger
{"systems": ["Uedama", "Niarja", "Sivala"], "threshold": 6}
```

---

### `remove_watch(label)`
Remove a watch by its label.

---

### `list_watches()`
List all configured watches with trigger counts and last trigger time.

---

### `check_watches_now()`
Immediately evaluate all watches and fire any that trigger. Useful for testing.

---

## Exploration Tools

### `get_scanning_walkthrough()`
Step-by-step guide to core probe scanning (10 steps, from launching probes to looting sites).

---

### `get_site_type_guide()`
Reference for all signature types: Relic, Data, Combat, Gas, Wormhole — with ISK potential, required analyzer, and priority.

---

### `get_hacking_guide()`
Complete hacking minigame guide: node types, utility subsystems, strategy, common mistakes, loot priority tip.

---

### `get_exploration_isk_guide()`
Realistic ISK expectations by security class (highsec vs lowsec), what affects earnings, when to graduate from highsec.

---

### `get_full_exploration_primer()`
All exploration knowledge in one call: scanning guide + site types + hacking guide + ISK expectations + quick reference card.

---

## Digest Tools

### `generate_weekly_digest(post_to_discord=False)`
Generate the weekly summary report.

**Parameters:**
- `post_to_discord` — whether to post a summary to Discord (default False)

**Returns:** path where the full report was saved, ISK P&L summary, report preview. Full report saved to `data/digests/`

---

## SDE Lookup Tools

### `lookup_item(name_or_id)`
Look up any item, ship, or module.

**Parameters:**
- `name_or_id` — item name (substring match) or numeric type ID

**Returns:** type_id, name, group, category, mass, volume, capacity; or list of matches if ambiguous

---

### `lookup_system(name_or_id)`
Look up a solar system.

**Parameters:**
- `name_or_id` — system name or numeric system ID

**Returns:** system_id, name, security, region, constellation; or list of matches if ambiguous

---

### `jumps_between(from_system, to_system)`
Shortest gate-jump path between two systems.

**Parameters:**
- `from_system` — system name or ID
- `to_system` — system name or ID

**Returns:** `from`, `to`, `jumps` (int), `reachable` (bool)

---

### `get_ship_specs(ship)`
Ship specifications from the SDE: slot layout, fitting resources, tank, navigation, targeting, drone capacity, and hardpoints.

**Parameters:**
- `ship` — ship name or numeric type ID

**Returns:** name, slot layout (high/mid/low/rig), CPU, powergrid, shield/armor/structure HP and resists, speed, agility, warp speed, targeting range, drone bandwidth/bay, turret/launcher hardpoints

---

### `get_module_specs(module)`
Module fitting specs from the SDE: resource usage, slot type, and meta level.

**Parameters:**
- `module` — module name or numeric type ID

**Returns:** name, CPU usage, powergrid usage, capacitor cost, slot type (high/mid/low/rig), calibration cost (rigs), meta level
