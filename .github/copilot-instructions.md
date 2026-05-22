# Copilot Instructions — VAEL Repository

Guidance for AI coding assistants working on this codebase. This is **not** Vael's runtime persona — for that, see [vael_system_prompt.txt](../vael_system_prompt.txt).

## ESI API Reference

The full ESI OpenAPI spec is at `docs/esi-swagger.json` (fetched by `script/esi-swagger.sh`).
When researching, planning, or implementing ESI-related features, consult this file for
endpoint paths, parameters, response schemas, and required scopes.

## What this repo is

VAEL is a Python MCP (Model Context Protocol) server that exposes 48 tools backed by EVE Online's ESI API, the Fuzzwork SDE SQLite mirror, and zKillboard. It is consumed by Claude Desktop, where a system prompt ([vael_system_prompt.txt](../vael_system_prompt.txt)) turns the raw tools into the "Vael" persona. There are also two parallel processes: a tkinter game overlay (`overlay.py`) and a background notifier (`notifier.py`) that pushes Discord/overlay alerts.

## Project layout

- `src/eve_agent/server.py` — MCP server entrypoint registering all tools via `@mcp.tool()`
- `src/eve_agent/tools/` — domain modules: `character.py`, `market.py`, `industry.py`, `skills.py`, `intel.py`
- `src/eve_agent/esi_client.py` — async ESI HTTP client (rate limits, retries, caching). Always use this; never hit ESI directly.
- `src/eve_agent/cache.py` — SQLite cache that respects ESI `Expires` headers
- `src/eve_agent/sde.py` — read-only queries against `data/sde.sqlite`
- `src/eve_agent/pilot_memory.py` — JSON-backed cross-session memory at `data/pilot_memory.json`
- `src/eve_agent/event_engine.py` + `notifier.py` + `discord_alerts.py` + `overlay.py` — the watch/alert pipeline
- `src/eve_agent/auth.py` — EVE SSO OAuth2 + PKCE, tokens encrypted via OS keyring
- `tests/test_all_tools.py` — single integration suite that hits live ESI; must pass before merging
- `docs/` — user-facing docs (`scopes.md`, `configuration.md`, `tools_reference.md`, `pilot-profile.md`)
- `vael_system_prompt.txt` — canonical Vael persona (pasted into Claude Desktop project)

## Conventions

- **Python 3.11+**, async-first. All tool functions are `async def`.
- **Tool registration:** every public capability is an `@mcp.tool()` in `server.py` that delegates to a domain module. Keep docstrings concrete — Claude reads them to decide when to call.
- **Generic wording in docstrings:** refer to "the capsuleer" / "the pilot", not a specific character name. Character-specific data belongs in runtime memory or `docs/pilot-profile.md`, never hardcoded.
- **Logging:** the `@mcp.tool()` wrapper in `server.py` logs each call as `log.info("tool: <name>(...)")`. Domain modules in `tools/` define a module logger (`log = logging.getLogger(__name__)`) for their own use but do not need to re-log the tool entry.
- **ESI access:** always through `ESIClient` as an async context manager (`async with ESIClient() as esi:`). Respect cache headers — don't bypass `cache.py`. Direct `httpx` usage is only acceptable for non-ESI endpoints (e.g. zKillboard in `intel.py`).
- **Errors:** tools should return `{"error": "..."}` dicts rather than raising, so the MCP layer surfaces them cleanly to Claude. Internal helpers (e.g. `_current_character_id()`) may raise — the tool wrapper catches and formats.
- **Money/numbers:** ISK is a float in raw ESI responses. Format with thousands separators in user-facing strings, keep raw values in API responses.
- **No write scopes.** This project is read-only by ESI policy. Do not add tools that mutate game state.

## Adding a new tool

1. Implement the async function in the appropriate `src/eve_agent/tools/<domain>.py` module.
2. Register it in `server.py` with `@mcp.tool()` and a one-line docstring that tells Claude when to call it.
3. Add a test in `tests/test_all_tools.py`.
4. Document it in `docs/tools_reference.md`.

## Testing

- Run `python tests/test_all_tools.py` — it hits live ESI, SDE, zKillboard, and Discord. Requires `.env` configured and tokens authenticated via `python -m eve_agent.auth`.
- There is no mock layer; tests are integration-only by design.

## Security & safety

- Never commit `.env`, tokens, or anything in `data/`.
- `data/tokens.json.enc` is encrypted via OS keyring; never log decrypted tokens.
- All third-party API access must include the configured `EVE_USER_AGENT` per CCP's ESI rules.
- Do not add features that automate gameplay, inject into the EVE client, or violate CCP's EULA/ToS.

## What not to do

- Don't refactor unrelated code while making a targeted change.
- Don't add docstrings, type hints, or comments to code you didn't modify.
- Don't introduce new dependencies without checking `requirements.txt` for an existing equivalent.
- Don't hardcode character names, IDs, or pilot-specific config in source — that belongs in `data/` or `.env`.
