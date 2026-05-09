"""
EVE Agent Overlay — transparent always-on HUD for EVE Online.

A small transparent window that floats above EVE showing live data:
system danger, wallet, skill queue countdown, active jobs, alerts.

Run:
    python -m eve_agent.overlay

Hotkeys:
    Ctrl+Shift+E  - toggle show/hide
    Ctrl+Shift+Q  - quit overlay

The overlay polls your MCP data every 30 seconds in the background.
Drag anywhere on the window to reposition.
Click any section to expand details in a popup.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import threading
import time
import tkinter as tk
from tkinter import font as tkfont
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
POLL_INTERVAL = 30       # seconds between data refreshes
BG_COLOR = "#0D0D0D"     # near-black background
BG_ALPHA = 0.88          # transparency (0.0 = invisible, 1.0 = opaque)
FG_PRIMARY = "#E8E6D9"   # main text
FG_SECONDARY = "#9B9990" # muted text
FG_GREEN = "#57C49A"     # positive / safe
FG_YELLOW = "#F5C842"    # warning
FG_RED = "#E85D5D"       # danger
FG_BLUE = "#5B9BD5"      # info
FG_AMBER = "#EF9F27"     # market / industry
ACCENT = "#3E3C38"       # border / divider

WINDOW_WIDTH = 280
COLLAPSED_HEIGHT = 36
EXPANDED_HEIGHT = 320


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
class OverlayData:
    """Holds the latest polled data for the overlay to display."""

    def __init__(self):
        self.char_name: str = "Loading..."
        self.isk: str = "---"
        self.system: str = "---"
        self.system_sec: float = 1.0
        self.danger_rating: int = 0
        self.ship: str = "---"
        self.docked: bool = True
        self.queue_skills: int = 0
        self.queue_days: float = 0
        self.current_training: str = "---"
        self.sp_total: int = 0
        self.active_jobs: int = 0
        self.open_orders: int = 0
        self.sell_value: float = 0
        self.alerts: list[str] = []
        self.last_updated: str = "Never"
        self.error: Optional[str] = None


# ---------------------------------------------------------------------------
# Background data fetcher
# ---------------------------------------------------------------------------
async def _fetch_data(data: OverlayData) -> None:
    """Fetch all overlay data asynchronously."""
    try:
        from eve_agent.tools.character import (
            get_character_summary, get_skill_overview, get_current_location
        )
        from eve_agent.tools.market import get_my_market_orders
        from eve_agent.tools.industry import get_active_industry_jobs
        from eve_agent.tools.intel import get_system_danger

        summary = await get_character_summary()
        data.char_name = summary.get("character_name", "Unknown")
        data.isk = f"{summary.get('isk_balance', 0):,.0f}"
        data.system = summary.get("location", "Unknown").split("(")[0].strip()
        data.ship = summary.get("current_ship", "Unknown")
        data.system_sec = summary.get("system_security", 1.0) or 1.0

        loc = await get_current_location()
        data.docked = loc.get("docked", True)
        system_name = loc.get("system_name", "")

        # Danger (only if not docked)
        if system_name and not data.docked:
            try:
                danger_result = await get_system_danger(system_name)
                data.danger_rating = danger_result.get("danger_rating", 0)
            except Exception:
                data.danger_rating = 0

        skills = await get_skill_overview()
        data.queue_skills = skills.get("queue_length", 0)
        data.sp_total = skills.get("total_sp", 0)
        ct = skills.get("currently_training")
        if ct:
            data.current_training = f"{ct.get('skill_name', '?')} L{ct.get('to_level', '?')}"
            finish = ct.get("finish_date", "")
            if finish:
                try:
                    fdt = datetime.fromisoformat(finish.replace("Z", "+00:00"))
                    days = (fdt - datetime.now(timezone.utc)).total_seconds() / 86400
                    data.queue_days = max(0, days)
                except Exception:
                    data.queue_days = 0
        else:
            data.current_training = "Queue empty!"
            data.queue_days = 0

        orders = await get_my_market_orders()
        data.open_orders = orders.get("open_sell_orders", 0) + orders.get("open_buy_orders", 0)
        data.sell_value = orders.get("total_sell_listing_value", 0)

        jobs = await get_active_industry_jobs()
        data.active_jobs = jobs.get("count", 0)

        # Build alert list
        alerts = []
        if data.queue_days < 1 and data.queue_days >= 0:
            alerts.append(f"QUEUE LOW: {data.queue_days * 24:.0f}h left")
        if data.danger_rating >= 8 and not data.docked:
            alerts.append(f"DANGER: {data.system} is {data.danger_rating}/10")
        data.alerts = alerts[:3]

        data.last_updated = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        data.error = None

    except Exception as e:
        data.error = str(e)[:60]
        log.warning("Overlay fetch error: %s", e)


def _run_fetch(data: OverlayData) -> None:
    """Run the async fetch in a thread."""
    asyncio.run(_fetch_data(data))


# ---------------------------------------------------------------------------
# Overlay window
# ---------------------------------------------------------------------------
class EVEOverlay:
    def __init__(self):
        self.data = OverlayData()
        self.expanded = True
        self._drag_x = 0
        self._drag_y = 0

        self.root = tk.Tk()
        self._setup_window()
        self._build_ui()
        self._start_polling()

        # Global hotkey (Windows only via keyboard module if installed, else skip)
        try:
            import keyboard
            keyboard.add_hotkey("ctrl+shift+e", self._toggle_expand)
            keyboard.add_hotkey("ctrl+shift+q", self.root.quit)
        except ImportError:
            pass

    def _setup_window(self) -> None:
        root = self.root
        root.title("Vael")
        root.overrideredirect(True)       # No title bar
        root.wm_attributes("-topmost", True)   # Always on top
        root.wm_attributes("-alpha", BG_ALPHA)
        root.configure(bg=BG_COLOR)
        root.geometry(f"{WINDOW_WIDTH}x{EXPANDED_HEIGHT}+20+20")
        root.resizable(False, False)

        # Drag binding
        root.bind("<Button-1>", self._on_click)
        root.bind("<B1-Motion>", self._on_drag)

    def _build_ui(self) -> None:
        root = self.root

        # Header bar
        self.header = tk.Frame(root, bg=ACCENT, height=28)
        self.header.pack(fill=tk.X, padx=0, pady=0)
        self.header.pack_propagate(False)

        tk.Label(
            self.header, text="  VAEL", bg=ACCENT, fg=FG_PRIMARY,
            font=("Consolas", 9, "bold"), anchor="w"
        ).pack(side=tk.LEFT, padx=4)

        self.status_dot = tk.Label(
            self.header, text="●", bg=ACCENT, fg=FG_GREEN,
            font=("Consolas", 8)
        )
        self.status_dot.pack(side=tk.LEFT)

        self.toggle_btn = tk.Button(
            self.header, text="-", bg=ACCENT, fg=FG_SECONDARY,
            font=("Consolas", 10, "bold"), relief="flat",
            command=self._toggle_expand, cursor="hand2",
            bd=0, padx=6,
        )
        self.toggle_btn.pack(side=tk.RIGHT)

        # Main content frame
        self.content = tk.Frame(root, bg=BG_COLOR)
        self.content.pack(fill=tk.BOTH, expand=True, padx=6, pady=4)

        # System & danger
        self.sys_frame = tk.Frame(self.content, bg=BG_COLOR)
        self.sys_frame.pack(fill=tk.X, pady=(0, 2))
        self.lbl_system = tk.Label(
            self.sys_frame, text="System: ---", bg=BG_COLOR, fg=FG_PRIMARY,
            font=("Consolas", 10), anchor="w"
        )
        self.lbl_system.pack(side=tk.LEFT)
        self.lbl_danger = tk.Label(
            self.sys_frame, text="", bg=BG_COLOR, fg=FG_GREEN,
            font=("Consolas", 9), anchor="e"
        )
        self.lbl_danger.pack(side=tk.RIGHT)

        self._divider()

        # ISK
        self.lbl_isk = tk.Label(
            self.content, text="ISK: ---", bg=BG_COLOR, fg=FG_GREEN,
            font=("Consolas", 10), anchor="w"
        )
        self.lbl_isk.pack(fill=tk.X)

        # Ship
        self.lbl_ship = tk.Label(
            self.content, text="Ship: ---", bg=BG_COLOR, fg=FG_SECONDARY,
            font=("Consolas", 9), anchor="w"
        )
        self.lbl_ship.pack(fill=tk.X)

        self._divider()

        # Skills
        self.lbl_skill = tk.Label(
            self.content, text="Training: ---", bg=BG_COLOR, fg=FG_BLUE,
            font=("Consolas", 9), anchor="w"
        )
        self.lbl_skill.pack(fill=tk.X)
        self.lbl_queue = tk.Label(
            self.content, text="Queue: ---", bg=BG_COLOR, fg=FG_SECONDARY,
            font=("Consolas", 9), anchor="w"
        )
        self.lbl_queue.pack(fill=tk.X)
        self.lbl_sp = tk.Label(
            self.content, text="SP: ---", bg=BG_COLOR, fg=FG_SECONDARY,
            font=("Consolas", 9), anchor="w"
        )
        self.lbl_sp.pack(fill=tk.X)

        self._divider()

        # Market & Industry
        self.lbl_orders = tk.Label(
            self.content, text="Orders: ---", bg=BG_COLOR, fg=FG_AMBER,
            font=("Consolas", 9), anchor="w"
        )
        self.lbl_orders.pack(fill=tk.X)
        self.lbl_jobs = tk.Label(
            self.content, text="Jobs: ---", bg=BG_COLOR, fg=FG_AMBER,
            font=("Consolas", 9), anchor="w"
        )
        self.lbl_jobs.pack(fill=tk.X)

        self._divider()

        # Alerts
        self.lbl_alert = tk.Label(
            self.content, text="", bg=BG_COLOR, fg=FG_YELLOW,
            font=("Consolas", 9), anchor="w", wraplength=260, justify="left"
        )
        self.lbl_alert.pack(fill=tk.X)

        # Footer
        self.lbl_updated = tk.Label(
            self.content, text="Last updated: never", bg=BG_COLOR, fg=FG_SECONDARY,
            font=("Consolas", 7), anchor="w"
        )
        self.lbl_updated.pack(fill=tk.X, pady=(4, 0))

    def _divider(self) -> None:
        tk.Frame(self.content, bg=ACCENT, height=1).pack(fill=tk.X, pady=2)

    def _update_ui(self) -> None:
        d = self.data

        if d.error:
            self.lbl_system.config(text=f"Error: {d.error}", fg=FG_RED)
            self.status_dot.config(fg=FG_RED)
            return

        self.status_dot.config(fg=FG_GREEN)

        # System
        sec = d.system_sec
        sec_color = FG_GREEN if sec >= 0.5 else FG_YELLOW if sec >= 0.0 else FG_RED
        self.lbl_system.config(
            text=f"  {d.system} ({sec:.1f})",
            fg=sec_color,
        )

        # Danger
        if not d.docked and d.danger_rating > 0:
            dr = d.danger_rating
            d_color = FG_RED if dr >= 7 else FG_YELLOW if dr >= 4 else FG_GREEN
            self.lbl_danger.config(text=f"DANGER {dr}/10", fg=d_color)
        else:
            self.lbl_danger.config(text="DOCKED" if d.docked else "", fg=FG_SECONDARY)

        # ISK
        self.lbl_isk.config(text=f"  ISK: {d.isk}")

        # Ship
        self.lbl_ship.config(text=f"  Ship: {d.ship}")

        # Skills
        self.lbl_skill.config(text=f"  Training: {d.current_training}")
        queue_text = (
            f"  Queue: {d.queue_days:.1f}d remaining ({d.queue_skills} skills)"
            if d.queue_skills > 0
            else "  Queue: EMPTY"
        )
        queue_color = FG_RED if d.queue_days < 1 else FG_SECONDARY
        self.lbl_queue.config(text=queue_text, fg=queue_color)
        self.lbl_sp.config(text=f"  SP: {d.sp_total:,}")

        # Market / Industry
        self.lbl_orders.config(
            text=f"  Orders: {d.open_orders} open | {d.sell_value:,.0f} ISK listed"
        )
        self.lbl_jobs.config(text=f"  Jobs: {d.active_jobs} active")

        # Alerts
        if d.alerts:
            self.lbl_alert.config(text="  ! " + "\n  ! ".join(d.alerts))
        else:
            self.lbl_alert.config(text="")

        # Footer
        self.lbl_updated.config(text=f"  Updated: {d.last_updated}")

    def _start_polling(self) -> None:
        """Start background polling thread."""
        self._poll()

    def _poll(self) -> None:
        """Fetch data in a background thread, then schedule next poll."""
        def fetch():
            _run_fetch(self.data)
            self.root.after(0, self._update_ui)

        t = threading.Thread(target=fetch, daemon=True)
        t.start()

        # Schedule next poll
        self.root.after(POLL_INTERVAL * 1000, self._poll)

    def _toggle_expand(self) -> None:
        self.expanded = not self.expanded
        if self.expanded:
            self.root.geometry(f"{WINDOW_WIDTH}x{EXPANDED_HEIGHT}")
            self.content.pack(fill=tk.BOTH, expand=True, padx=6, pady=4)
            self.toggle_btn.config(text="-")
        else:
            self.content.pack_forget()
            self.root.geometry(f"{WINDOW_WIDTH}x{COLLAPSED_HEIGHT}")
            self.toggle_btn.config(text="+")

    def _on_click(self, event) -> None:
        self._drag_x = event.x
        self._drag_y = event.y

    def _on_drag(self, event) -> None:
        x = self.root.winfo_x() + event.x - self._drag_x
        y = self.root.winfo_y() + event.y - self._drag_y
        self.root.geometry(f"+{x}+{y}")

    def run(self) -> None:
        self.root.mainloop()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> int:
    logging.basicConfig(level=logging.INFO)
    print("Starting EVE Agent Overlay...")
    print("Hotkeys: Ctrl+Shift+E = toggle, Ctrl+Shift+Q = quit")
    print("Or drag the window to reposition it.")
    overlay = EVEOverlay()
    overlay.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
