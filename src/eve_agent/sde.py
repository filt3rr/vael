"""
Static Data Export (SDE) queries.

A small, fast wrapper around the Fuzzwork SDE SQLite mirror. Used everywhere
we need to convert a numeric ID from ESI into a human-readable name or
properties (item types, ship hulls, solar systems, regions, stations,
blueprints, skill groups, etc.).

This module is sync (the SDE is a local file — no need for async). Other
modules can call it freely from async contexts; SQLite is fast enough that
blocking briefly is fine.

Public API:
    get_type(type_id)              -> dict with name/group/category/volume/etc
    get_system(system_id)          -> dict with name/security/region/constellation
    get_region(region_id)          -> dict with name
    get_station(station_id)        -> dict with name/system/etc
    search_types(name_fragment)    -> list of matching {id, name, group_id}
    search_systems(name_fragment)  -> list of matching {id, name, security}
    get_skill_group(group_id)      -> dict
    list_skills_in_group(group_id) -> list of skill types
    distance_between(sys_a, sys_b) -> jump count via shortest route (None if unreachable)
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from collections import deque
from functools import lru_cache
from typing import Any, Optional

from eve_agent.config import SDE_DB_PATH


log = logging.getLogger(__name__)


# Thread-local connection so SQLite usage is safe under concurrency.
_thread_local = threading.local()


def _conn() -> sqlite3.Connection:
    """Return a thread-local read-only SQLite connection to the SDE."""
    if getattr(_thread_local, "conn", None) is None:
        if not SDE_DB_PATH.exists():
            raise FileNotFoundError(
                f"SDE not found at {SDE_DB_PATH}. Download it from "
                f"https://www.fuzzwork.co.uk/dump/sqlite-latest.sqlite.bz2 "
                f"and decompress to data/sde.sqlite."
            )
        # Open in read-only mode via URI
        uri = f"file:{SDE_DB_PATH.as_posix()}?mode=ro"
        c = sqlite3.connect(uri, uri=True, check_same_thread=False)
        c.row_factory = sqlite3.Row
        _thread_local.conn = c
    return _thread_local.conn


def _row_to_dict(row: Optional[sqlite3.Row]) -> Optional[dict]:
    return dict(row) if row is not None else None


# ---------------------------------------------------------------------------
# Type / item lookup
# ---------------------------------------------------------------------------
@lru_cache(maxsize=8192)
def get_type(type_id: int) -> Optional[dict]:
    """Return basic info for an item/ship type, or None."""
    row = _conn().execute(
        """
        SELECT
            t.typeID         AS type_id,
            t.typeName       AS name,
            t.description    AS description,
            t.groupID        AS group_id,
            g.groupName      AS group_name,
            g.categoryID     AS category_id,
            c.categoryName   AS category_name,
            t.mass           AS mass,
            t.volume         AS volume,
            t.capacity       AS capacity,
            t.published      AS published
        FROM invTypes t
        LEFT JOIN invGroups g     ON g.groupID    = t.groupID
        LEFT JOIN invCategories c ON c.categoryID = g.categoryID
        WHERE t.typeID = ?
        """,
        (type_id,),
    ).fetchone()
    return _row_to_dict(row)


def get_type_name(type_id: int) -> str:
    """Best-effort name for a type id (returns 'Unknown (id)' if not found)."""
    t = get_type(type_id)
    return t["name"] if t else f"Unknown type ({type_id})"


def search_types(
    name_fragment: str,
    limit: int = 25,
    published_only: bool = True,
) -> list[dict]:
    """
    Find item types matching the fragment, ranked:
      1. Exact match (case-insensitive)
      2. Prefix match (name starts with fragment)
      3. Word-boundary match (e.g. ' rifter' or 'rifter ')
      4. Substring match (anywhere in name)
    Within each rank, shorter names come first.
    """
    pub_clause = " AND t.published = 1" if published_only else ""
    sql = f"""
        SELECT
            t.typeID    AS type_id,
            t.typeName  AS name,
            t.groupID   AS group_id,
            g.groupName AS group_name,
            CASE
                WHEN LOWER(t.typeName) = LOWER(?) THEN 0
                WHEN LOWER(t.typeName) LIKE LOWER(?) THEN 1
                WHEN LOWER(t.typeName) LIKE LOWER(?) OR LOWER(t.typeName) LIKE LOWER(?) THEN 2
                ELSE 3
            END AS rank
        FROM invTypes t
        LEFT JOIN invGroups g ON g.groupID = t.groupID
        WHERE t.typeName LIKE ? COLLATE NOCASE
        {pub_clause}
        ORDER BY rank ASC, LENGTH(t.typeName) ASC, t.typeName ASC
        LIMIT ?
    """
    frag = name_fragment
    rows = _conn().execute(sql, (
        frag,                # exact
        f"{frag}%",          # prefix
        f"% {frag}%",        # word boundary leading
        f"%{frag} %",        # word boundary trailing
        f"%{frag}%",         # general WHERE filter
        limit,
    )).fetchall()
    return [dict({k: v for k, v in dict(r).items() if k != "rank"}) for r in rows]


# ---------------------------------------------------------------------------
# Solar system / region / constellation
# ---------------------------------------------------------------------------
@lru_cache(maxsize=8192)
def get_system(system_id: int) -> Optional[dict]:
    """Return system name, security, region, constellation, etc."""
    row = _conn().execute(
        """
        SELECT
            s.solarSystemID    AS system_id,
            s.solarSystemName  AS name,
            s.security         AS security,
            s.constellationID  AS constellation_id,
            c.constellationName AS constellation_name,
            s.regionID         AS region_id,
            r.regionName       AS region_name
        FROM mapSolarSystems s
        LEFT JOIN mapConstellations c ON c.constellationID = s.constellationID
        LEFT JOIN mapRegions r        ON r.regionID = s.regionID
        WHERE s.solarSystemID = ?
        """,
        (system_id,),
    ).fetchone()
    return _row_to_dict(row)


def get_system_name(system_id: int) -> str:
    s = get_system(system_id)
    return s["name"] if s else f"Unknown system ({system_id})"


@lru_cache(maxsize=2048)
def get_region(region_id: int) -> Optional[dict]:
    row = _conn().execute(
        "SELECT regionID AS region_id, regionName AS name FROM mapRegions WHERE regionID = ?",
        (region_id,),
    ).fetchone()
    return _row_to_dict(row)


def search_systems(name_fragment: str, limit: int = 25) -> list[dict]:
    rows = _conn().execute(
        """
        SELECT
            s.solarSystemID   AS system_id,
            s.solarSystemName AS name,
            s.security        AS security,
            r.regionName      AS region_name
        FROM mapSolarSystems s
        LEFT JOIN mapRegions r ON r.regionID = s.regionID
        WHERE s.solarSystemName LIKE ? COLLATE NOCASE
        ORDER BY s.solarSystemName
        LIMIT ?
        """,
        (f"%{name_fragment}%", limit),
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Stations
# ---------------------------------------------------------------------------
@lru_cache(maxsize=4096)
def get_station(station_id: int) -> Optional[dict]:
    """Return NPC station info. (Player-owned structures aren't in the SDE.)"""
    row = _conn().execute(
        """
        SELECT
            st.stationID      AS station_id,
            st.stationName    AS name,
            st.solarSystemID  AS system_id,
            s.solarSystemName AS system_name,
            st.regionID       AS region_id,
            r.regionName      AS region_name,
            st.stationTypeID  AS type_id,
            t.typeName        AS type_name
        FROM staStations st
        LEFT JOIN mapSolarSystems s ON s.solarSystemID = st.solarSystemID
        LEFT JOIN mapRegions r      ON r.regionID = st.regionID
        LEFT JOIN invTypes t        ON t.typeID = st.stationTypeID
        WHERE st.stationID = ?
        """,
        (station_id,),
    ).fetchone()
    return _row_to_dict(row)


# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------
def get_skill_group(group_id: int) -> Optional[dict]:
    row = _conn().execute(
        """
        SELECT groupID AS group_id, groupName AS name, categoryID AS category_id
        FROM invGroups
        WHERE groupID = ? AND categoryID = 16  -- 16 = skills
        """,
        (group_id,),
    ).fetchone()
    return _row_to_dict(row)


def list_skills_in_group(group_id: int) -> list[dict]:
    rows = _conn().execute(
        """
        SELECT typeID AS type_id, typeName AS name
        FROM invTypes
        WHERE groupID = ? AND published = 1
        ORDER BY typeName
        """,
        (group_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_all_skill_groups() -> list[dict]:
    rows = _conn().execute(
        """
        SELECT groupID AS group_id, groupName AS name
        FROM invGroups
        WHERE categoryID = 16 AND published = 1
        ORDER BY groupName
        """
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Routing — BFS for shortest jump path
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _build_jump_graph() -> dict[int, set[int]]:
    """Build adjacency map of system_id -> set of neighbor system_ids."""
    log.info("Building SDE jump graph (one-time, ~5500 systems)...")
    rows = _conn().execute(
        "SELECT fromSolarSystemID, toSolarSystemID FROM mapSolarSystemJumps"
    ).fetchall()
    graph: dict[int, set[int]] = {}
    for row in rows:
        a, b = row[0], row[1]
        graph.setdefault(a, set()).add(b)
        graph.setdefault(b, set()).add(a)
    log.info("Jump graph built: %d systems.", len(graph))
    return graph


def distance_between(
    from_system_id: int,
    to_system_id: int,
    max_jumps: int = 60,
) -> Optional[int]:
    """
    Return the shortest gate-jump count between two systems via BFS,
    or None if unreachable within max_jumps.
    """
    if from_system_id == to_system_id:
        return 0

    graph = _build_jump_graph()
    if from_system_id not in graph or to_system_id not in graph:
        return None

    visited = {from_system_id}
    queue = deque([(from_system_id, 0)])
    while queue:
        node, dist = queue.popleft()
        if dist >= max_jumps:
            continue
        for neighbor in graph.get(node, ()):
            if neighbor == to_system_id:
                return dist + 1
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append((neighbor, dist + 1))
    return None


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    print(f"Opening SDE at: {SDE_DB_PATH}")
    print(f"  size: {SDE_DB_PATH.stat().st_size / (1024*1024):.1f} MB")
    print()

    print("== Item type lookups ==")
    # Tritanium
    print("  Type 34:           ", get_type_name(34))
    # Rifter
    print("  Type 587:          ", get_type_name(587))
    # PLEX
    print("  Type 44992:        ", get_type_name(44992))

    print()
    print("== System lookups ==")
    # Jita
    jita = get_system(30000142)
    print(f"  System 30000142:   {jita['name']} "
          f"(security {jita['security']:.2f}, region {jita['region_name']})")
    # Amarr
    amarr = get_system(30002187)
    print(f"  System 30002187:   {amarr['name']} "
          f"(security {amarr['security']:.2f}, region {amarr['region_name']})")

    print()
    print("== Search ==")
    matches = search_types("rifter", limit=5)
    print(f"  Search 'rifter' returned {len(matches)} matches:")
    for m in matches:
        print(f"    [{m['type_id']:>7}] {m['name']}  ({m['group_name']})")

    print()
    print("== Routing ==")
    # Jita -> Amarr (well-known ~10 jumps)
    d = distance_between(30000142, 30002187)
    print(f"  Jita -> Amarr:     {d} jumps")
    # Same system
    print(f"  Jita -> Jita:      {distance_between(30000142, 30000142)} jumps")

    print()
    print("== Skill groups ==")
    groups = get_all_skill_groups()
    print(f"  {len(groups)} skill groups in the game.")
    print(f"  First 3: {[g['name'] for g in groups[:3]]}")

    sys.exit(0)