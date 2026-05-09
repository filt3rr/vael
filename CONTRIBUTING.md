# Contributing to VAEL

Contributions are welcome. Here's how the project is structured and what to expect.

---

## Before You Start

- Check existing [issues](../../issues) and [discussions](../../discussions) to avoid duplicating work
- For significant changes, open an issue first to discuss direction
- All PRs must pass `python tests/test_all_tools.py` (requires a valid `.env` with real EVE credentials)

---

## Adding a New MCP Tool

Tools live in `src/eve_agent/tools/` (grouped by domain) or as standalone modules in `src/eve_agent/`.

**1. Write the function**

Add an async function to the appropriate tool module:

```python
async def get_my_new_thing(param: str) -> dict:
    """Clear docstring explaining what this returns."""
    cid = _current_character_id()
    async with ESIClient() as esi:
        data = await esi.get(f"/characters/{cid}/thing/", character_id=cid)
    return {"result": data}
```

**2. Register it in `server.py`**

```python
@mcp.tool()
async def get_my_new_thing(param: str) -> dict[str, Any]:
    """
    Clear description for Claude. This is what Vael reads to decide when
    to call the tool. Be specific about what the tool returns and when to use it.
    """
    log.info("tool: get_my_new_thing(%s)", param)
    return await your_module.get_my_new_thing(param)
```

**3. Add a test in `test_all_tools.py`**

```python
await t("get_my_new_thing",
    your_module.get_my_new_thing("test_param"),
    lambda r: f"result={r.get('result')}")
```

**4. Document it in `docs/tools_reference.md`**

Add a section with parameters, return values, and a usage note.

---

## Adding a New Notification Channel

Edit `src/eve_agent/notifier.py`. The `notify()` function dispatches to all configured channels:

```python
def notify(title: str, message: str, duration: int = 8, discord_color: str = "neutral") -> None:
    # Add your channel here
    if telegram_configured():
        telegram_send(title, message)
```

Add corresponding configuration to `.env.example` and `docs/configuration.md`.

---

## Adding a New Watch Type

Edit `src/eve_agent/event_engine.py`:

1. Add the type to `VALID_WATCH_TYPES`
2. Write an `async def _check_my_watch(watch: dict) -> Optional[dict]` function
3. Add it to `WATCH_CHECKERS`
4. Add a cooldown to `WATCH_COOLDOWNS`
5. Document in `docs/tools_reference.md` under `add_watch()`

---

## ESI Guidelines

When adding ESI calls:

- Always inject `User-Agent` (handled by `ESIClient` automatically)
- Always cache responses — use `esi.get()` not raw `httpx`
- Use `get_paginated()` for endpoints with `X-Pages` headers
- Add typed exceptions — catch `ESIAuthError`, `ESINotFoundError` specifically
- Test with `use_cache=False` in the notifier but allow caching in tools

---

## Code Style

- Python 3.11+ type hints throughout
- `async/await` for all ESI calls
- Sync functions for SDE queries (local SQLite, fast enough)
- All functions return `dict` (JSON-serializable)
- Log with `log.info("tool: function_name(%s)", param)` at the start of every tool
- No hardcoded character IDs — always call `auth.list_characters()[0].character_id`

---

## Testing

Tests require a valid `.env` with real credentials and active tokens:

```bash
python -m eve_agent.auth        # If not already authenticated
python tests/test_all_tools.py  # Run the full suite
```

Tests make live API calls to ESI and zKillboard. Expect ~30-60 seconds for the full suite.

For CI environments without credentials, skip the live tests — we don't mock ESI responses because the point of these tools is live data accuracy.

---

## Vael's Persona

If you're contributing to the system prompt or persona documentation:

- Vael is a **grizzled veteran**, not a helpful assistant
- He gives **direct opinions**, not "here are your options"
- He uses **EVE jargon** naturally — ISK, SP, T2, d-scan, local, gate camp
- He **remembers things** across sessions and references them
- He **pushes back** when the plan is bad
- He is **genuinely invested** in the pilot's success

Don't soften the persona. Players respond to authenticity.
