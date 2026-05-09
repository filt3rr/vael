# VAEL — EVE Online AI Agent

> A grizzled veteran in your corner. Real-time EVE Online intelligence powered by Claude AI.

[!\[Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://python.org)
[!\[MCP](https://img.shields.io/badge/MCP-1.0%2B-purple)](https://modelcontextprotocol.io)
[!\[License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[!\[EVE Online](https://img.shields.io/badge/EVE%20Online-ESI%20API-silver)](https://esi.evetech.net)

VAEL is a personal AI agent for EVE Online built on the [Model Context Protocol](https://modelcontextprotocol.io). It connects Claude Desktop to your EVE character's live data — wallet, skills, market orders, assets, industry jobs, fittings — and wraps it in the persona of a grizzled 10-year veteran who gives you real, opinionated advice rather than just returning data.

!\[VAEL Overlay Screenshot](docs/images/overlay\_preview.png)

\---

## What It Does

**Talks to you like a fellow pilot, not a search engine.**

> \*"Your skill queue empties in 4 hours. Hacking III lands tonight which shores up your data sites. You've got 7 sell orders open and Tritanium is trending down — if you've got inventory, move it now. What's the plan?"\*

**Uses live data, every time.**

Every answer pulls fresh ESI data. No guessing. No stale numbers.

**Runs in the background.**

An always-on HUD overlay, Discord alerts to your phone, and a background notifier watching for skill completions, market fills, industry jobs, and custom conditions you configure.

\---

## Features

### AI Partner (Claude Desktop via MCP)

* 44 tools across character, market, industry, skills, intel, memory, P\&L, and exploration
* Persistent pilot memory across sessions — Vael remembers your goals, mistakes, and milestones
* SITREP protocol — Vael checks your situation before you even ask
* Grizzled veteran persona with opinions, dark humor, and direct advice

### Live EVE Data (ESI API)

* Wallet, skills, assets, location, ship, fittings
* Market orders (open + history), wallet journal
* Industry jobs (active + completed)
* Skill queue with training time calculations
* Ship prerequisite checking

### Market Intelligence

* Live buy/sell prices across all 5 major hubs (Jita, Amarr, Dodixie, Rens, Hek)
* Arbitrage detection across hubs
* 30-day price history with trend analysis
* Manufacturing cost calculator with live mineral prices
* P\&L tracking by activity (trading, exploration, missions, industry)

### PvP Intel (zKillboard)

* System danger rating (1-10) from 7-day kill data
* Character public dossier — corp, alliance, killboard stats
* Real-time recent kills in any system
* Regional kill heat maps
* Undock risk assessment for your current location

### Always-On Infrastructure

* **Game overlay** — transparent HUD floating over EVE (system, ISK, queue, orders, alerts)
* **Discord alerts** — Vael pings your phone for skill completions, order fills, industry jobs
* **Background notifier** — polls ESI every 5 minutes across all channels
* **Configurable watches** — set custom triggers (price thresholds, danger spikes, ISK milestones)
* **Weekly digest** — auto-generated Sunday report with ISK performance, skill progress, and Vael's assessment

### Exploration Tools

* Step-by-step scanning walkthrough
* Site type guide (Relic, Data, Combat, Gas, Wormhole)
* Hacking minigame guide (node types, strategy, common mistakes)
* ISK expectations by security class
* Ship fitting recommendations calibrated to your actual skill levels

\---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Claude Desktop                       │
│              (conversations with Vael)                  │
└───────────────────────┬─────────────────────────────────┘
                        │ MCP protocol (stdio)
┌───────────────────────▼─────────────────────────────────┐
│                  MCP Server (44 tools)                  │
│   character · market · industry · skills · intel        │
│   memory · P\&L · events · fittings · exploration        │
└──────┬────────────────┬────────────────┬────────────────┘
       │                │                │
┌──────▼──────┐  ┌──────▼──────┐  ┌─────▼──────────┐
│  ESI Client │  │ SDE SQLite  │  │ zKillboard API │
│  (cached)   │  │  (528 MB)   │  │   (public)     │
└─────────────┘  └─────────────┘  └────────────────┘

Parallel processes:
├── overlay.py    — transparent game HUD (tkinter)
├── notifier.py   — background ESI poller + Discord alerts
└── Claude Desktop — AI conversations
```

\---

## Quick Start

### Prerequisites

* Python 3.11+
* [Claude Desktop](https://claude.ai/download)
* An EVE Online account
* A Discord server (optional, for phone alerts)

### 1\. Clone and install

```bash
git clone https://github.com/YOUR\_USERNAME/eve-agent.git
cd eve-agent
python -m venv .venv

# Windows
.venv\\Scripts\\activate

# Mac/Linux
source .venv/bin/activate

pip install -r requirements.txt
pip install -e .
```

### 2\. Register your EVE application

Go to [developers.eveonline.com](https://developers.eveonline.com) and create a new application:

* **Connection type:** Authentication \& API Access
* **Callback URL:** `http://localhost:8765/callback`
* **Scopes:** See [docs/scopes.md](docs/scopes.md) for the full list

Save your **Client ID** and **Secret Key**.

### 3\. Configure

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```env
EVE\_CLIENT\_ID=your\_client\_id
EVE\_CLIENT\_SECRET=your\_client\_secret
EVE\_CALLBACK\_URL=http://localhost:8765/callback
EVE\_USER\_AGENT=eve-agent/0.1 (your\_email@example.com)
DISCORD\_WEBHOOK\_URL=https://discord.com/api/webhooks/...  # optional
```

### 4\. Download the Static Data Export

```bash
python scripts/download\_sde.py
```

This downloads and decompresses the Fuzzwork SDE mirror (\~528 MB) to `data/sde.sqlite`.

### 5\. Authenticate with EVE SSO

```bash
python -m eve\_agent.auth
```

A browser window opens. Log in with your EVE account and approve the scopes. Your tokens are stored encrypted using your OS keyring.

### 6\. Test everything

```bash
python tests/test\_all\_tools.py
```

All tests should pass. This validates live ESI connectivity, SDE queries, market data, zKillboard, and Discord.

### 7\. Connect to Claude Desktop

```bash
python scripts/install\_mcp.py
```

This writes the MCP server configuration to Claude Desktop's config file. Restart Claude Desktop.

### 8\. Set up Vael's persona

In your Claude Desktop project:

1. Create a new Project called "EVE ONLINE"
2. Click **Instructions** and paste the contents of `docs/vael\_system\_prompt.txt`
3. Upload `docs/filt3r\_pilot\_profile\_template.txt` as a project file (customize with your character details)

### 9\. Start the background processes

**Overlay** (in a separate terminal):

```bash
python -m eve\_agent.overlay
```

**Notifier** (in another terminal):

```bash
python -m eve\_agent.notifier
```

\---

## Usage

Open Claude Desktop, navigate to your EVE project, and start talking:

```
Hey Vael
```

Vael runs a SITREP automatically — checks your wallet, skill queue, market orders, and industry jobs, then briefs you on what needs attention.

```
Check what I have fitted on my Heron
```

```
I want to go exploration scanning — walk me through it
```

```
Should I undock in Uedama right now? My ship is worth 80M ISK
```

```
What's the Tritanium price trend over the last 30 days and is it worth buying now?
```

```
Calculate the manufacturing profit for 10 Rifters at ME10
```

```
Set a watch to alert me when Tritanium drops below 3.50 in Jita
```

```
Generate my weekly digest
```

\---

## Project Structure

```
eve-agent/
├── src/eve\_agent/
│   ├── auth.py              # EVE SSO OAuth2 + PKCE + encrypted tokens
│   ├── cache.py             # ESI response cache (SQLite, respects Expires headers)
│   ├── config.py            # Settings loaded from .env
│   ├── discord\_alerts.py    # Discord webhook integration
│   ├── esi\_client.py        # Async ESI HTTP client (rate limits, retries, caching)
│   ├── event\_engine.py      # Configurable watch system with smart triggers
│   ├── exploration\_guide.py # Scanning, site types, hacking guide knowledge base
│   ├── fittings.py          # Ship fitting reader + exploration fit recommender
│   ├── notifier.py          # Background polling + multi-channel alert delivery
│   ├── overlay.py           # Transparent game HUD (tkinter)
│   ├── pilot\_memory.py      # Persistent cross-session memory for Vael
│   ├── pnl\_engine.py        # ISK velocity, P\&L tracking, activity analysis
│   ├── sde.py               # Static Data Export queries (items, systems, routing)
│   ├── server.py            # MCP server entrypoint (44 tools)
│   ├── weekly\_digest.py     # Auto-generated weekly summary report
│   └── tools/
│       ├── character.py     # Character data, wallet, assets, location
│       ├── industry.py      # Jobs, blueprints, manufacturing cost calculator
│       ├── intel.py         # zKillboard danger ratings, character intel
│       ├── market.py        # Prices, history, orders, hub comparison
│       └── skills.py        # Queue, training time, prerequisites, suggestions
├── tests/
│   └── test\_all\_tools.py    # Full integration test suite (48 tests)
├── scripts/
│   ├── download\_sde.py      # Downloads and decompresses the SDE
│   └── install\_mcp.py       # Configures Claude Desktop MCP connection
├── docs/
│   ├── scopes.md            # Required ESI OAuth scopes
│   ├── vael\_system\_prompt.txt
│   ├── configuration.md
│   ├── tools\_reference.md
│   └── faq.md
├── data/                    # Runtime data (gitignored)
├── .env.example
├── pyproject.toml
├── requirements.txt
└── README.md
```

\---

## Configuration Reference

See [docs/configuration.md](docs/configuration.md) for all configuration options including:

* ESI rate limit tuning
* Poll intervals
* Overlay position and appearance
* Discord alert categories
* Watch cooldown periods

\---

## Tools Reference

44 tools across 9 domains. See [docs/tools\_reference.md](docs/tools_reference.md) for the full list with parameters and examples.

**Quick reference:**

|Domain|Tools|
|-|-|
|Character|`get\_character\_summary` · `get\_wallet\_balance` · `get\_skill\_overview` · `get\_current\_location` · `get\_asset\_summary` · `list\_recent\_wallet\_journal`|
|Fittings|`get\_saved\_fittings` · `get\_active\_ship\_equipment` · `recommend\_exploration\_fit`|
|Market|`get\_market\_price` · `compare\_hub\_prices` · `get\_market\_history` · `get\_my\_market\_orders`|
|Industry|`get\_active\_industry\_jobs` · `get\_blueprint\_info` · `calculate\_manufacturing\_cost`|
|Skills|`calculate\_training\_time` · `can\_i\_fly` · `get\_skill\_queue` · `suggest\_next\_skills`|
|Intel|`get\_system\_danger` · `get\_character\_intel` · `get\_recent\_kills\_in\_system` · `should\_i\_undock` · `get\_regional\_kill\_activity`|
|P\&L|`get\_pnl\_summary` · `get\_isk\_velocity` · `analyze\_trading\_performance` · `get\_activity\_breakdown` · `project\_isk\_growth`|
|Memory|`read\_pilot\_memory` · `write\_pilot\_memory` · `append\_pilot\_memory` · `log\_isk\_snapshot` · `get\_isk\_history`|
|Watches|`add\_watch` · `remove\_watch` · `list\_watches` · `check\_watches\_now`|
|Exploration|`get\_scanning\_walkthrough` · `get\_site\_type\_guide` · `get\_hacking\_guide` · `get\_exploration\_isk\_guide` · `get\_full\_exploration\_primer`|
|Digest|`generate\_weekly\_digest`|
|SDE|`lookup\_item` · `lookup\_system` · `jumps\_between`|

\---

## Security

* OAuth2 tokens are stored **encrypted** using your OS keyring (Windows Credential Manager, macOS Keychain, Linux Secret Service)
* The `.env` file is gitignored and never committed
* All ESI access is **read-only** by default (no write scopes)
* The agent never transmits your credentials to any third party
* Rate limiting is respected per CCP's ESI guidelines

See [SECURITY.md](SECURITY.md) for the full security model.

\---

## Contributing

Contributions welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for:

* How to add new MCP tools
* How to add new notification channels
* How to extend the SDE query layer
* Testing requirements (all PRs must pass `test\_all\_tools.py`)

\---

## Acknowledgments

* [CCP Games](https://www.ccpgames.com) for the ESI API and EVE Online
* [Fuzzwork](https://www.fuzzwork.co.uk) for the SDE SQLite mirror
* [zKillboard](https://zkillboard.com) for the public kill data API
* [Anthropic](https://anthropic.com) for Claude and the MCP SDK
* The EVE Online third-party developer community

\---

## License

MIT License — see [LICENSE](LICENSE) for details.

This project is not affiliated with CCP Games. EVE Online is a trademark of CCP hf.

Copyright (c) 2026 Tyler Harb

\---

## Disclaimer

VAEL is a read-only intelligence tool. It does not automate gameplay, inject into the EVE client, or violate CCP's EULA or Terms of Service. It uses only the official ESI API with proper OAuth2 authentication and respects all CCP rate limiting guidelines.

