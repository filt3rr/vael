"""
Configure Claude Desktop to connect to the EVE Agent MCP server.

Run:
    python scripts/install_mcp.py

Writes the MCP server entry to Claude Desktop's config file.
Backs up any existing config before modifying.
"""

import json
import shutil
import sys
from pathlib import Path


def find_config_path() -> Path:
    """Find Claude Desktop's config file for the current platform."""
    import platform
    os_name = platform.system()

    if os_name == "Windows":
        appdata = Path.home() / "AppData" / "Roaming" / "Claude"
        return appdata / "claude_desktop_config.json"
    elif os_name == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    elif os_name == "Linux":
        return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"
    else:
        raise RuntimeError(f"Unsupported platform: {os_name}")


def find_python_exe() -> Path:
    """Find the Python executable in the current environment."""
    return Path(sys.executable)


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    python_exe = find_python_exe()

    print(f"Project root:  {project_root}")
    print(f"Python:        {python_exe}")

    try:
        cfg_path = find_config_path()
    except RuntimeError as e:
        print(f"Error: {e}")
        return 1

    print(f"Config file:   {cfg_path}")
    print()

    # Make sure Claude Desktop's config dir exists
    cfg_path.parent.mkdir(parents=True, exist_ok=True)

    # Load existing config or start fresh
    config = {}
    if cfg_path.exists():
        try:
            config = json.loads(cfg_path.read_text(encoding="utf-8"))
            print(f"Existing config loaded ({len(config.get('mcpServers', {}))} servers).")
        except json.JSONDecodeError:
            print("Warning: existing config is not valid JSON — starting fresh.")
            # Backup the broken file
            backup = cfg_path.with_suffix(".json.bak")
            shutil.copy2(cfg_path, backup)
            print(f"Backed up broken config to {backup}")
        # Backup any valid existing config
        backup = cfg_path.with_suffix(f".json.bak")
        if cfg_path.exists():
            shutil.copy2(cfg_path, backup)
            print(f"Backup saved to {backup}")
    else:
        print("No existing config — creating new.")

    # Build the server entry
    server_entry = {
        "command": str(python_exe),
        "args": ["-m", "eve_agent.server"],
        "cwd": str(project_root),
    }

    if "mcpServers" not in config:
        config["mcpServers"] = {}

    if "eve-agent" in config["mcpServers"]:
        print("Updating existing 'eve-agent' entry.")
    else:
        print("Adding new 'eve-agent' entry.")

    config["mcpServers"]["eve-agent"] = server_entry

    # Write without BOM (critical on Windows)
    cfg_path.write_text(
        json.dumps(config, indent=2),
        encoding="utf-8",
    )

    print()
    print("Config written successfully.")
    print()
    print("Next step: fully quit and relaunch Claude Desktop.")
    print("The eve-agent MCP server will appear in the connector list.")
    print()
    print("Server entry:")
    print(json.dumps({"eve-agent": server_entry}, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
