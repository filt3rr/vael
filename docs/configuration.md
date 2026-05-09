# Configuration Reference

## Environment Variables (`.env`)

Copy `.env.example` to `.env` and fill in your values. Never commit `.env` to git.

| Variable | Required | Description |
|----------|----------|-------------|
| `EVE_CLIENT_ID` | Yes | Client ID from developers.eveonline.com |
| `EVE_CLIENT_SECRET` | Yes | Secret key from developers.eveonline.com |
| `EVE_CALLBACK_URL` | Yes | Must be `http://localhost:8765/callback` |
| `EVE_USER_AGENT` | Yes | Contact info for CCP (email or Discord). Format: `eve-agent/0.1 (contact@example.com)` |
| `DISCORD_WEBHOOK_URL` | No | Discord webhook for phone alerts. Get from: Server Settings → Integrations → Webhooks |

### Writing `.env` on Windows

PowerShell's `Out-File` adds a UTF-8 BOM that breaks Python's dotenv parser. Use this instead:

```powershell
$lines = @(
    "EVE_CLIENT_ID=your_id",
    "EVE_CLIENT_SECRET=your_secret",
    "EVE_CALLBACK_URL=http://localhost:8765/callback",
    "EVE_USER_AGENT=eve-agent/0.1 (you@example.com)",
    "DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/..."
)
[System.IO.File]::WriteAllLines("$PWD\.env", $lines, [System.Text.UTF8Encoding]::new($false))
```

---

## ESI Client Settings

Edit `src/eve_agent/esi_client.py` to tune these constants:

```python
POLL_INTERVAL = 30          # Overlay refresh rate (seconds)
GLOBAL_CONCURRENCY = 20     # Max concurrent ESI requests
MAX_RETRIES = 4             # Retries on 5xx errors
INITIAL_BACKOFF = 1.0       # First retry wait (seconds, doubles each retry)
ERROR_LIMIT_PAUSE_THRESHOLD = 20  # Slow down when error budget drops below this
```

---

## Notifier Settings

Edit `src/eve_agent/notifier.py`:

```python
POLL_INTERVAL = 300   # How often to poll ESI (seconds). Min recommended: 60
```

**Per-watch cooldowns** (in `event_engine.py`) prevent repeat alerts:

```python
WATCH_COOLDOWNS = {
    "price_below":  3600,   # 1 hour between alerts
    "price_above":  3600,
    "danger_spike": 1800,   # 30 minutes
    "isk_below":    3600,
    "isk_above":    86400,  # 24 hours (milestones shouldn't repeat)
    "skill_soon":   3600,
    "route_danger": 1800,
}
```

---

## Overlay Settings

Edit `src/eve_agent/overlay.py`:

```python
POLL_INTERVAL = 30      # Data refresh rate (seconds)
BG_ALPHA = 0.88         # Window transparency (0.0 = invisible, 1.0 = opaque)
WINDOW_WIDTH = 280      # Overlay width in pixels
```

**Positioning:** Drag the overlay window anywhere. Position resets on restart. To set a persistent default position, change the geometry string in `_setup_window()`:

```python
root.geometry(f"{WINDOW_WIDTH}x{EXPANDED_HEIGHT}+20+20")
#                                                 ^x ^y  (pixels from top-left)
```

**Hotkeys** (requires `keyboard` package):
- `Ctrl+Shift+E` — toggle expand/collapse
- `Ctrl+Shift+Q` — quit overlay

---

## Claude Desktop MCP Configuration

Located at `%APPDATA%\Claude\claude_desktop_config.json` on Windows.

The `scripts/install_mcp.py` script writes this automatically. Manual format:

```json
{
  "mcpServers": {
    "eve-agent": {
      "command": "C:\\path\\to\\eve-agent\\.venv\\Scripts\\python.exe",
      "args": ["-m", "eve_agent.server"],
      "cwd": "C:\\path\\to\\eve-agent"
    }
  }
}
```

---

## Data Files

All runtime data lives in `data/` (gitignored):

| File | Description |
|------|-------------|
| `data/sde.sqlite` | Static Data Export (~528 MB). Download with `scripts/download_sde.py` |
| `data/cache.sqlite` | ESI response cache. Safe to delete — rebuilds automatically |
| `data/tokens.json.enc` | Encrypted OAuth tokens. Delete to force re-authentication |
| `data/pilot_memory.json` | Vael's persistent memory. Human-readable JSON |
| `data/notifier_state.json` | Notifier deduplication state |
| `data/watches.json` | Configured event watches |
| `data/logs/server.log` | MCP server log |
| `data/logs/notifier.log` | Notifier log |
| `data/digests/` | Weekly digest reports |

---

## Token Encryption

OAuth refresh tokens are encrypted using Fernet symmetric encryption. The encryption key is stored in your OS keyring:

- **Windows:** Windows Credential Manager
- **macOS:** Keychain
- **Linux:** Secret Service (libsecret)

If you lose the keyring entry, delete `data/tokens.json.enc` and re-run `python -m eve_agent.auth`.
