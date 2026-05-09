"""
EVE Agent Notifier v3 — rebuilt with full Phase III capabilities.

Channels:
  - Windows toast notifications (win10toast-click)
  - Discord webhook alerts
  - Console fallback

Checks every poll cycle:
  - Skill queue (completion, low queue, empty)
  - Market orders (filled, expiring)
  - Industry jobs (complete)
  - Mail (new)
  - Contracts (accepted/completed)
  - Custom watches (via event_engine)
  - Compound: ISK velocity snapshots

Run:
    python -m eve_agent.notifier
    python -m eve_agent.notifier --once     (single poll and exit)
    python -m eve_agent.notifier --discord  (enable Discord even if not default)
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from eve_agent import auth
from eve_agent.config import DATA_DIR, LOGS_DIR, ensure_dirs
from eve_agent.esi_client import ESIClient
from eve_agent.sde import get_type
from eve_agent.discord_alerts import alert as discord_alert, alert_skill, alert_industry, _is_configured as discord_configured


log = logging.getLogger(__name__)
STATE_PATH = DATA_DIR / "notifier_state.json"
POLL_INTERVAL = 300  # 5 minutes


# ---------------------------------------------------------------------------
# Toast setup
# ---------------------------------------------------------------------------
_toaster = None
_toast_backend = "console"

try:
    from win10toast_click import ToastNotifier as _T
    _toaster = _T()
    _toast_backend = "win10toast"
except Exception:
    pass


def notify(title: str, message: str, duration: int = 8, discord_color: str = "neutral") -> None:
    """Fire notification across all configured channels."""
    log.info("NOTIFY: %s | %s", title, message)

    # Toast
    if _toast_backend == "win10toast":
        try:
            _toaster.show_toast(title, message, duration=duration, threaded=True)
        except Exception as e:
            log.debug("Toast failed: %s", e)

    # Discord
    if discord_configured():
        discord_alert(title, message, color=discord_color)

    # Console always
    print(f"\n{'='*55}")
    print(f">>> {title}")
    print(f"    {message}")
    print(f"{'='*55}")


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
def _load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_state(state: dict) -> None:
    ensure_dirs()
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Poll functions
# ---------------------------------------------------------------------------
async def check_skill_queue(esi: ESIClient, cid: int, state: dict) -> None:
    try:
        queue = await esi.get(
            f"/characters/{cid}/skillqueue/", character_id=cid, use_cache=False
        )
    except Exception as e:
        log.warning("Skill queue check failed: %s", e)
        return

    now = datetime.now(timezone.utc)
    completed = state.setdefault("completed_skills", [])
    active = []

    for q in queue:
        finish = q.get("finish_date")
        if not finish:
            continue
        try:
            fdt = datetime.fromisoformat(finish.replace("Z", "+00:00"))
        except ValueError:
            continue

        if fdt <= now:
            key = f"{q['skill_id']}:{q.get('finished_level')}"
            if key not in completed:
                skill = get_type(q["skill_id"])
                name = skill["name"] if skill else f"Skill {q['skill_id']}"
                level = q.get("finished_level")
                notify(
                    "Skill Training Complete",
                    f"{name} to Level {level} finished!",
                    discord_color="skill",
                )
                completed.append(key)
        else:
            active.append(q)

    state["completed_skills"] = completed[-200:]

    # Empty queue
    if not active:
        if not state.get("notified_empty_queue"):
            notify(
                "Skill Queue Empty",
                "Queue finished — add your next skill now.",
                discord_color="warning",
            )
            state["notified_empty_queue"] = True
    else:
        state["notified_empty_queue"] = False

    # Low queue warning (< 24h remaining)
    if active:
        try:
            last_finish = datetime.fromisoformat(
                active[-1]["finish_date"].replace("Z", "+00:00")
            )
            hours_left = (last_finish - now).total_seconds() / 3600
            warned_at = state.get("warned_low_queue_at", 0) or 0
            if hours_left < 24 and time.time() - warned_at > 43200:
                notify(
                    "Skill Queue Running Low",
                    f"Only {hours_left:.1f}h of training left. Plan your next skills.",
                    discord_color="warning",
                )
                state["warned_low_queue_at"] = time.time()
        except Exception:
            pass


async def check_market_orders(esi: ESIClient, cid: int, state: dict) -> None:
    try:
        history = await esi.get(
            f"/characters/{cid}/orders/history/", character_id=cid, use_cache=False
        )
    except Exception as e:
        log.warning("Order history check failed: %s", e)
        return

    seen = set(state.setdefault("notified_orders", []))
    new_seen = set(seen)

    for o in history[:100]:
        oid = o["order_id"]
        if oid in seen:
            continue
        if o.get("volume_remain") == 0:
            type_info = get_type(o["type_id"])
            name = type_info["name"] if type_info else f"Type {o['type_id']}"
            kind = "Buy" if o.get("is_buy_order") else "Sell"
            notify(
                f"{kind} Order Filled",
                f"{o['volume_total']:,}x {name} @ {o['price']:,.2f} ISK",
                discord_color="market",
            )
        new_seen.add(oid)

    state["notified_orders"] = list(new_seen)[-500:]


async def check_industry_jobs(esi: ESIClient, cid: int, state: dict) -> None:
    try:
        jobs = await esi.get(
            f"/characters/{cid}/industry/jobs/",
            character_id=cid,
            params={"include_completed": "true"},
            use_cache=False,
        )
    except Exception as e:
        log.warning("Industry jobs check failed: %s", e)
        return

    notified = set(state.setdefault("notified_jobs", []))
    now_ts = datetime.now(timezone.utc).isoformat()

    for j in jobs:
        if j["job_id"] in notified:
            continue
        end = j.get("end_date", "")
        if end and end <= now_ts:
            product = get_type(j.get("product_type_id")) if j.get("product_type_id") else None
            pname = product["name"] if product else "unknown item"
            activity_map = {
                1: "Manufacturing", 3: "TE Research", 4: "ME Research",
                5: "Copying", 8: "Invention",
            }
            activity = activity_map.get(j.get("activity_id", 0), "Industry")
            notify(
                f"{activity} Complete",
                f"{j.get('runs', 1)}x {pname} ready to deliver.",
                discord_color="industry",
            )
            notified.add(j["job_id"])

    state["notified_jobs"] = list(notified)[-500:]


async def check_new_mail(esi: ESIClient, cid: int, state: dict) -> None:
    try:
        mail = await esi.get(
            f"/characters/{cid}/mail/", character_id=cid, use_cache=False
        )
    except Exception as e:
        log.warning("Mail check failed: %s", e)
        return

    if not mail:
        return

    last_seen = state.get("last_mail_id", 0)
    new_mail = [m for m in mail if m.get("mail_id", 0) > last_seen]

    if new_mail and last_seen > 0:
        count = len(new_mail)
        latest = new_mail[0]
        subject = latest.get("subject", "(no subject)")[:60]
        notify(
            f"New Mail ({count})",
            subject,
            discord_color="info",
        )

    newest_id = max((m.get("mail_id", 0) for m in mail), default=last_seen)
    state["last_mail_id"] = newest_id


async def check_contracts(esi: ESIClient, cid: int, state: dict) -> None:
    try:
        contracts = await esi.get(
            f"/characters/{cid}/contracts/", character_id=cid, use_cache=False
        )
    except Exception as e:
        log.warning("Contracts check failed: %s", e)
        return

    seen = set(state.setdefault("notified_contracts", []))

    for c in contracts:
        key = f"{c['contract_id']}:{c.get('status', '')}"
        if key in seen:
            continue
        status = c.get("status", "")
        if status in ("finished", "finished_contractor", "accepted"):
            notify(
                f"Contract {status.replace('_', ' ').title()}",
                f"{c.get('type', 'Contract').title()} contract #{c['contract_id']}.",
                discord_color="success",
            )
        seen.add(key)

    state["notified_contracts"] = list(seen)[-200:]


async def check_isk_snapshot(esi: ESIClient, cid: int, state: dict) -> None:
    """Record ISK snapshot for velocity tracking."""
    last_snapshot = state.get("last_isk_snapshot_at", 0) or 0
    if time.time() - last_snapshot < 3600:  # Max 1 snapshot per hour
        return
    try:
        from eve_agent.pilot_memory import log_isk_snapshot
        wallet = await esi.get(f"/characters/{cid}/wallet/", character_id=cid)
        if isinstance(wallet, (int, float)):
            log_isk_snapshot(float(wallet), "notifier auto-snapshot")
            state["last_isk_snapshot_at"] = time.time()
    except Exception as e:
        log.debug("ISK snapshot failed: %s", e)


async def check_custom_watches(state: dict) -> None:
    """Run custom event engine watches."""
    try:
        from eve_agent.event_engine import check_all_watches
        result = await check_all_watches(send_discord=True, send_toast=True)
        if result.get("triggered", 0) > 0:
            log.info("Custom watches triggered: %d", result["triggered"])
    except Exception as e:
        log.warning("Custom watch check failed: %s", e)


# ---------------------------------------------------------------------------
# Weekly digest scheduler
# ---------------------------------------------------------------------------
async def maybe_run_weekly_digest(state: dict) -> None:
    """Run weekly digest on Sundays."""
    now = datetime.now(timezone.utc)
    if now.weekday() != 6:  # 6 = Sunday
        return
    last_digest = state.get("last_digest_date", "")
    today = now.strftime("%Y-%m-%d")
    if last_digest == today:
        return

    try:
        from eve_agent.weekly_digest import generate_digest, save_digest, post_digest_to_discord
        log.info("Running weekly digest...")
        report = await generate_digest()
        await save_digest(report)
        if discord_configured():
            await post_digest_to_discord(report)
        state["last_digest_date"] = today
        notify(
            "Weekly Digest Ready",
            f"Your weekly summary has been generated and saved.",
            discord_color="info",
        )
    except Exception as e:
        log.warning("Weekly digest failed: %s", e)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
async def run_watcher(run_once: bool = False) -> None:
    chars = auth.list_characters()
    if not chars:
        print("No authenticated character. Run: python -m eve_agent.auth")
        return

    char = chars[0]
    cid = char.character_id

    print(f"Notifier running for {char.character_name} (id={cid})")
    print(f"Poll interval:  {POLL_INTERVAL}s")
    print(f"Toast backend:  {_toast_backend}")
    print(f"Discord alerts: {'enabled' if discord_configured() else 'not configured (add DISCORD_WEBHOOK_URL to .env)'}")
    print(f"State file:     {STATE_PATH}")
    print("Press Ctrl+C to stop.\n")

    notify("Vael Online", f"Notifier started for {char.character_name}.", discord_color="success")

    state = _load_state()

    async with ESIClient() as esi:
        while True:
            log.debug("Poll cycle starting.")
            try:
                await check_skill_queue(esi, cid, state)
                await check_market_orders(esi, cid, state)
                await check_industry_jobs(esi, cid, state)
                await check_new_mail(esi, cid, state)
                await check_contracts(esi, cid, state)
                await check_isk_snapshot(esi, cid, state)
                await check_custom_watches(state)
                await maybe_run_weekly_digest(state)
                _save_state(state)
                log.debug("Poll cycle complete.")
            except Exception:
                log.exception("Unhandled error in poll cycle")

            if run_once:
                break

            await asyncio.sleep(POLL_INTERVAL)


def main() -> int:
    ensure_dirs()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(LOGS_DIR / "notifier.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    run_once = "--once" in sys.argv
    try:
        asyncio.run(run_watcher(run_once=run_once))
    except KeyboardInterrupt:
        print("\nNotifier stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
