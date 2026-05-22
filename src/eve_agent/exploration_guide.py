"""
Exploration guide — Vael's knowledge base for teaching scanning and sites.

This module gives Vael the ability to walk the capsuleer through:
  - Setting up probes and scanning
  - Identifying site types
  - Running Relic and Data sites efficiently
  - Deciding which sites to run and which to skip
  - Understanding the hacking minigame
  - Loot table expectations and ISK potential

These are knowledge tools — they return structured guidance that Vael
interprets and delivers in character.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Site type reference
# ---------------------------------------------------------------------------
SITE_TYPES = {
    "Relic": {
        "analyzer": "Relic Analyzer I/II",
        "security_range": "All (highsec, lowsec, nullsec, wormhole)",
        "isk_potential": {
            "highsec": "1-20M ISK per site",
            "lowsec": "10-80M ISK per site",
            "nullsec_wormhole": "30-500M+ ISK per site",
        },
        "site_names": [
            "Crumbling/Ruined/Decayed/Pristine [faction] Relic Site",
            "Sansha's Nation Relic Site",
            "Guristas Relic Site",
            "Angel Cartel Relic Site",
        ],
        "what_drops": "Salvage components, ancient relics, Intact/Malfunctioning/Wrecked components that sell on market",
        "priority": "HIGHEST — always run these",
        "vael_note": "Relic sites are your bread and butter. A single good highsec relic pays for an hour of mission running. In wormholes they can pay for a week.",
    },
    "Data": {
        "analyzer": "Data Analyzer I/II",
        "security_range": "All",
        "isk_potential": {
            "highsec": "500K-5M ISK per site",
            "lowsec": "2-20M ISK per site",
            "nullsec_wormhole": "5-50M ISK per site",
        },
        "site_names": [
            "Crumbling/Ruined/Decayed/Pristine [faction] Data Site",
            "Sleeper Data Cache (wormhole)",
        ],
        "what_drops": "Decryptors, datacores, skill books — less consistent value than Relic",
        "priority": "MEDIUM — run if no Relic sites available",
        "vael_note": "Data sites are the consolation prize. Run them if that's all you've got, skip them if you have Relics to hit.",
    },
    "Combat": {
        "analyzer": "None — combat sites require combat ships",
        "security_range": "All",
        "isk_potential": {"all": "Varies — usually need a combat ship"},
        "site_names": ["Hideaway", "Refuge", "Den", "Yard", "Rally Point"],
        "what_drops": "Bounties, modules, faction loot",
        "priority": "SKIP for exploration Heron",
        "vael_note": "Your Heron can't fight. Bookmark combat anomalies and come back with a combat ship, or just ignore them.",
    },
    "Gas": {
        "analyzer": "None — gas harvesting needs a gas harvester module",
        "security_range": "All",
        "isk_potential": {"all": "Varies — requires Gas Cloud Harvester"},
        "site_names": ["Ordinary/Sizeable/Bountiful/Vast [gas] Cloud"],
        "what_drops": "Gas used in booster manufacturing — good ISK but needs different fit",
        "priority": "SKIP for now",
        "vael_note": "Gas is good money but needs different skills and a different fit. Come back to this later.",
    },
    "Wormhole": {
        "analyzer": "N/A — these are wormholes, not sites",
        "security_range": "Found in all space",
        "isk_potential": {"all": "Access to better relic/data sites inside"},
        "site_names": ["K162", "Various class designations"],
        "what_drops": "Wormhole leads to J-space with better exploration rewards",
        "priority": "ADVANCED — enter only when ready",
        "vael_note": "Don't go into wormholes yet. If you get stuck in one you'll have to self-destruct your ship to get out. Save this for when you understand the mechanics.",
    },
}

# Signature scan results
SIGNATURE_TYPES = {
    "Cosmic Signature": "Needs probes to identify — could be relic, data, combat, gas, or wormhole",
    "Cosmic Anomaly": "No probes needed — shows in your probe scanner automatically. Usually combat sites.",
    "Unknown": "Could be anything — probe it down to 100%",
}


# ---------------------------------------------------------------------------
# Hacking minigame guide
# ---------------------------------------------------------------------------
HACKING_GUIDE = {
    "overview": (
        "The hacking minigame is a logic puzzle on a grid. "
        "You start at one node and must reach the System Core to win. "
        "Along the way: reveal nodes, avoid or defeat Defensive Subsystems, "
        "collect Utility Subsystems (buffs), and reach the Core."
    ),
    "node_types": {
        "Empty node": "Safe to move through, no effect.",
        "System Core": "Your target. Defeat it to win the site. Click it to engage.",
        "Firewall": "Defensive system. Must reduce HP to 0 to pass. Fights back.",
        "Anti-Virus": "Stronger defensive system. Higher HP, fights back harder.",
        "Restoration Node": "Repairs the Core's HP every cycle. Find and kill these first.",
        "Polymorphic Shield": "Temporary defense boost on adjacent nodes.",
        "Data Cache": "Contains random Utility Subsystem — usually worth revealing.",
        "Kernel Rot": "Destroys a random node — useful if surrounded by defenses.",
        "Defensive Subsystem": "Generic term for nodes that attack you.",
    },
    "utility_subsystems": {
        "Transposition": "Teleport to any revealed node — great for bypassing defenses.",
        "Kernel Rot": "Destroys an adjacent node — use to kill Restoration Nodes.",
        "Self Repair": "Restores your coherence — use when low HP.",
        "Polymorphic Shield": "Temporary defense buff — use before attacking hard nodes.",
        "Secondary Vector": "Reduces target's HP by 20 — combo with your attack.",
    },
    "strategy": [
        "1. Open the site by approaching within 2500m and pressing Activate (F).",
        "2. Click nodes methodically — reveal the board before engaging defenses.",
        "3. Kill Restoration Nodes immediately — they undo your progress on the Core.",
        "4. Collect Data Cache nodes — they usually contain Utility Subsystems.",
        "5. Save Transposition for emergencies — it's your escape hatch.",
        "6. Attack the Core only when your path is clear of major threats.",
        "7. If your coherence (HP) drops below 30, use Self Repair before continuing.",
        "8. If you fail, wait 900 seconds (15 min) — the site resets and you can try again.",
    ],
    "common_mistakes": [
        "Clicking the Core immediately — it's usually surrounded by defenses, you'll fail.",
        "Ignoring Restoration Nodes — they will undo all your Core damage.",
        "Using Transposition too early — save it for when you're cornered.",
        "Forgetting to approach within 2500m before activating — the module won't cycle.",
        "Warping off mid-hack — you'll lose progress and the site may despawn.",
    ],
    "loot_tip": (
        "After hacking a container, loot erupts into space as floating cans. "
        "You have about 120 seconds before they start disappearing. "
        "Prioritize the shiniest (named) items first — they're worth most. "
        "Don't try to loot everything if there are lots of cans — you'll run out of time."
    ),
}


# ---------------------------------------------------------------------------
# Step by step scanning guide
# ---------------------------------------------------------------------------
SCANNING_STEPS = [
    {
        "step": 1,
        "title": "Open probe scanner",
        "action": "Press Alt+P (or click the scanner icon in your HUD). The probe scanner window opens.",
        "tip": "You'll see two types of results: Cosmic Anomalies (no probes needed) and Cosmic Signatures (need probes).",
    },
    {
        "step": 2,
        "title": "Launch probes",
        "action": "Right-click your Core Probe Launcher in your high slot and select Launch Probes. 8 probes deploy.",
        "tip": "Make sure you have Core Scanner Probes loaded, not Combat Scanner Probes.",
    },
    {
        "step": 3,
        "title": "Open system map",
        "action": "Press F10 (or click the solar system map button). You'll see your probes arranged around your ship.",
        "tip": "Zoom out until you can see the whole system.",
    },
    {
        "step": 4,
        "title": "Arrange probes",
        "action": "Click 'Scan Formation' in the probe window to auto-arrange into a sphere formation. Move the formation to cover the system center.",
        "tip": "For your first scan, just hit Scan — the default formation covers most of a highsec system.",
    },
    {
        "step": 5,
        "title": "Scan",
        "action": "Click the Scan button in the probe window. Results appear as colored spheres in the map. Red = weak signal, yellow = medium, green = strong.",
        "tip": "Signatures below 25% show as spheres, 25-75% as circles, above 75% as dots. You want dots.",
    },
    {
        "step": 6,
        "title": "Identify signature types",
        "action": "Look at the probe scanner results. Each signature has a type label. Unknown = needs more probing. If it says Relic Site or Data Site, it's identified.",
        "tip": "Hover over the colored shapes in the map to see which signature they correspond to.",
    },
    {
        "step": 7,
        "title": "Focus probes",
        "action": "Click a signature in the scanner list. Probes jump to focus on it. Reduce probe radius (slider in probe window) to get more precision.",
        "tip": "Go from max radius -> 4 AU -> 2 AU -> 1 AU -> 0.5 AU. Scan at each size. Stop when it hits 100%.",
    },
    {
        "step": 8,
        "title": "Warp to site",
        "action": "Once a signature reaches 100%, right-click it in the probe scanner and select Warp To. Choose 100km for safety on your first time.",
        "tip": "Warp to 100km first to assess the site before warping to 0. Some sites have NPCs near the warp-in.",
    },
    {
        "step": 9,
        "title": "Approach and hack",
        "action": "Approach a can within 2500m. Right-click and Activate your Relic or Data Analyzer. The hacking minigame starts.",
        "tip": "In highsec relic sites there are no NPCs — just cans. Approach and hack them all.",
    },
    {
        "step": 10,
        "title": "Loot and move on",
        "action": "Loot all cans. Open the next signature. Repeat until you've cleared the system or it's time to move.",
        "tip": "Keep moving — depleted sites respawn elsewhere. Explore chains of connected systems for best results.",
    },
]


# ---------------------------------------------------------------------------
# ISK expectations by activity
# ---------------------------------------------------------------------------
ISK_EXPECTATIONS = {
    "highsec_exploration": {
        "hourly_range": "5-30M ISK/hour",
        "realistic_average": "10-15M ISK/hour",
        "peak_single_site": "20M ISK",
        "what_affects_it": [
            "Archaeology/Hacking skill level (higher = more containers cracked)",
            "Scan strength (higher = faster clears, more sites per hour)",
            "Region (Caldari/Amarr space tends to have Guristas/Sansha relics)",
            "Luck (relic drops are random — some sites are worth 500K, some 15M)",
        ],
        "vael_note": "Highsec exploration is learning money. It funds your skills and ships while you get the mechanics down. Once you're comfortable, lowsec pays 3-5x more for the same sites.",
    },
    "lowsec_exploration": {
        "hourly_range": "20-80M ISK/hour",
        "realistic_average": "30-50M ISK/hour",
        "peak_single_site": "80M ISK",
        "what_affects_it": [
            "Your willingness to warp to 0 and move fast",
            "Reading local chat for hostiles",
            "D-scan discipline while hacking",
            "Choosing low-traffic pipe systems vs busy hubs",
        ],
        "vael_note": "Lowsec is where exploration starts paying real money. The sites are the same, just richer drops. The catch is other players can and will try to kill you. Move fast, d-scan constantly, warp out the moment local spikes.",
    },
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def get_scanning_walkthrough() -> dict:
    """Return the complete step-by-step scanning guide."""
    return {
        "steps": SCANNING_STEPS,
        "total_steps": len(SCANNING_STEPS),
        "summary": "Core probe scanning: launch probes -> arrange -> scan -> focus -> warp -> hack -> loot",
    }


def get_site_type_guide() -> dict:
    """Return the site type reference with priorities and ISK estimates."""
    return {
        "site_types": SITE_TYPES,
        "priority_order": ["Relic", "Data", "Gas (later)", "Combat (different ship)"],
        "skip_in_heron": ["Combat", "Gas"],
        "wormhole_warning": "Avoid wormholes until you fully understand how to navigate them",
    }


def get_hacking_guide() -> dict:
    """Return the full hacking minigame guide."""
    return HACKING_GUIDE


def get_isk_expectations() -> dict:
    """Return realistic ISK expectations for exploration by security class."""
    return ISK_EXPECTATIONS


def get_full_exploration_primer() -> dict:
    """
    Return everything a new explorer needs: scanning steps,
    site types, hacking guide, and ISK expectations.
    The full package.
    """
    return {
        "scanning_guide": get_scanning_walkthrough(),
        "site_types": get_site_type_guide(),
        "hacking_guide": get_hacking_guide(),
        "isk_expectations": get_isk_expectations(),
        "quick_reference": {
            "most_important_skill": "Archaeology — Relic sites pay most",
            "fit_essentials": "Core Probe Launcher, Relic Analyzer, Data Analyzer, 2x Gravity Cap Rig",
            "first_priority_sites": "Relic Sites only until confident",
            "safe_security_to_start": "0.5+ highsec systems with low local population",
            "d_scan_habit": "Press V every 30 seconds while hacking. Uncheck all, check ships. Strangers in local = warp out.",
        },
    }
