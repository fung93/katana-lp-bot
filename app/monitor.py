"""Phase 3 monitoring: sustained out/in-range + campaign-expiry alerts.

Run modes (all share run_check + the Neon-backed state):
  * ``python -m app.monitor``            one-shot pass (for a plain scheduler).
  * ``python -m app.monitor --loop N``   loop run_check for ~N seconds, then exit
    (GitHub Actions job: a long run kept alive by schedule + concurrency, so the
    check effectively runs every 60s without depending on your PC).
  * in-process loop (opt-in)             bot.py drives monitor_loop() if
    INPROCESS_MONITOR=1 (an always-on single host).

State lives in Neon (monitor_state) so it survives across separate runs. Alerts
go out via the Telegram HTTP API (no PTB needed).

Neon idle-backoff: when you hold NO open positions, checks drop to every
IDLE_INTERVAL_SEC so the database can sleep; with positions open, every
MONITOR_INTERVAL_SEC.

Alert rule (sustained, so a flickering price doesn't spam you):
  * out of range for >= sustain   -> "out of range" alert (IL attached)
  * back in range for >= sustain  -> "back in range" alert (only after an out)
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from datetime import datetime, timezone

import httpx

from .chain import get_slot0
from .config import (
    get_allowed_user_id,
    get_pool_address,
    get_rpc_url,
    get_telegram_token,
)
from .db import get_cursor
from .merkl import fetch_campaign
from .positions import il_at_price, list_open
from .tickmath import tick_to_price

log = logging.getLogger("katana-lp-bot.monitor")

MONITOR_INTERVAL_SEC = int(os.environ.get("MONITOR_INTERVAL_SEC", "60"))
IDLE_INTERVAL_SEC = int(os.environ.get("IDLE_INTERVAL_SEC", "600"))  # no positions -> back off
RANGE_SUSTAIN_SEC = int(os.environ.get("RANGE_SUSTAIN_SEC", "300"))  # 5 minutes
EXPIRY_THRESHOLD_DAYS = 7


# --------------------------------------------------------------------------- #
# Pure alert state machine (unit-tested in tests/test_monitor.py)
# --------------------------------------------------------------------------- #
def step(state: dict | None, in_range: bool, now: float,
         sustain: float) -> tuple[dict, str | None]:
    """Advance one position's alert state. Returns (new_state, 'out'|'in'|None)."""
    if state is None or state["in_range"] != in_range:
        prev_out = state["alerted_out"] if state else False
        return ({"in_range": in_range, "since": now, "alerted": False,
                 "alerted_out": prev_out}, None)
    if state["alerted"] or (now - state["since"]) < sustain:
        return state, None
    new = dict(state, alerted=True)
    if not in_range:
        new["alerted_out"] = True
        return new, "out"
    if state["alerted_out"]:
        new["alerted_out"] = False
        return new, "in"
    return new, None  # initial in-range: nothing to recover from


# --------------------------------------------------------------------------- #
# Alert text
# --------------------------------------------------------------------------- #
def _out_alert(p, price: float) -> str:
    il_usd, il_pct = il_at_price(p, price)
    return (f"⚠️ Position #{p.id[:8]} OUT of range (>{RANGE_SUSTAIN_SEC // 60} min)\n"
            f"ETH ${price:,.2f}  ·  range ${p.price_low:,.0f}–${p.price_high:,.0f}\n"
            f"IL now: -${abs(il_usd):,.2f} ({il_pct:+.1%})")


def _in_alert(p, price: float) -> str:
    return (f"✅ Position #{p.id[:8]} back IN range\n"
            f"ETH ${price:,.2f}  ·  range ${p.price_low:,.0f}–${p.price_high:,.0f}")


# --------------------------------------------------------------------------- #
# Outbound via Telegram HTTP API (no PTB dependency in the cron path)
# --------------------------------------------------------------------------- #
def send_telegram(text: str) -> None:
    resp = httpx.post(
        f"https://api.telegram.org/bot{get_telegram_token()}/sendMessage",
        json={"chat_id": get_allowed_user_id(), "text": text},
        timeout=20,
    )
    resp.raise_for_status()


# --------------------------------------------------------------------------- #
# Alert state in Neon (a scheduled run has no memory between invocations)
# --------------------------------------------------------------------------- #
def load_states() -> dict:
    with get_cursor(commit=False) as cur:
        cur.execute("select position_id, in_range, since, alerted, alerted_out "
                    "from monitor_state")
        return {str(r[0]): {"in_range": r[1], "since": float(r[2]),
                            "alerted": r[3], "alerted_out": r[4]}
                for r in cur.fetchall()}


def save_state(pos_id: str, st: dict) -> None:
    with get_cursor() as cur:
        cur.execute(
            """
            insert into monitor_state
              (position_id, in_range, since, alerted, alerted_out, updated_at)
            values (%s, %s, %s, %s, %s, now())
            on conflict (position_id) do update set
              in_range = excluded.in_range, since = excluded.since,
              alerted = excluded.alerted, alerted_out = excluded.alerted_out,
              updated_at = now()
            """,
            (pos_id, st["in_range"], st["since"], st["alerted"], st["alerted_out"]),
        )


def _meta_get(key: str) -> str | None:
    with get_cursor(commit=False) as cur:
        cur.execute("select value from monitor_meta where key = %s", (key,))
        row = cur.fetchone()
        return row[0] if row else None


def _meta_set(key: str, value: str) -> None:
    with get_cursor() as cur:
        cur.execute(
            """insert into monitor_meta (key, value, updated_at) values (%s, %s, now())
               on conflict (key) do update set value = excluded.value, updated_at = now()""",
            (key, value),
        )


# --------------------------------------------------------------------------- #
# One monitoring pass (shared by every run mode)
# --------------------------------------------------------------------------- #
def run_check(send=send_telegram) -> tuple[int, int]:
    """Do one pass; send any alerts; return (alerts_sent, open_positions)."""
    positions = list_open()
    if not positions:
        return 0, 0
    slot0 = get_slot0(get_rpc_url(), get_pool_address())
    price = tick_to_price(slot0.tick)
    now = time.time()
    states = load_states()
    sent = 0
    for p in positions:
        new_state, alert = step(states.get(p.id), p.in_range(slot0.tick), now,
                                RANGE_SUSTAIN_SEC)
        save_state(p.id, new_state)
        if alert == "out":
            send(_out_alert(p, price)); sent += 1
            log.info("OUT alert for %s", p.id[:8])
        elif alert == "in":
            send(_in_alert(p, price)); sent += 1
            log.info("IN alert for %s", p.id[:8])
    sent += _maybe_expiry(send)
    return sent, len(positions)


def _maybe_expiry(send) -> int:
    today = datetime.now(timezone.utc).date().isoformat()
    if _meta_get("last_expiry_date") == today:
        return 0
    _meta_set("last_expiry_date", today)
    try:
        camp = fetch_campaign()
    except Exception:
        return 0
    if camp.is_expiring(EXPIRY_THRESHOLD_DAYS):
        end = datetime.fromtimestamp(camp.end_ts, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M UTC")
        send(f"⏳ Merkl campaign ends in {camp.days_to_end():.1f} days ({end}).\n"
             f"Incentive APR {camp.apr_pct:.1f}% drops to ~0 when it lapses.")
        return 1
    return 0


def _sleep_for(n_open: int) -> int:
    return MONITOR_INTERVAL_SEC if n_open else IDLE_INTERVAL_SEC


# --------------------------------------------------------------------------- #
# Bounded loop (GitHub Actions job) and in-process loop (opt-in)
# --------------------------------------------------------------------------- #
def run_loop(max_seconds: float, send=send_telegram) -> None:
    """Loop run_check for ~max_seconds, then return so the job can hand off."""
    deadline = time.time() + max_seconds
    log.info("loop for %.0fs (active %ss / idle %ss)",
             max_seconds, MONITOR_INTERVAL_SEC, IDLE_INTERVAL_SEC)
    while time.time() < deadline:
        try:
            _, n_open = run_check(send)
        except Exception as exc:
            log.warning("loop tick failed: %s", exc)
            n_open = 0
        nap = _sleep_for(n_open)
        if time.time() + nap >= deadline:
            break
        time.sleep(nap)


async def monitor_loop() -> None:
    log.info("in-process monitor loop started (active %ss / idle %ss)",
             MONITOR_INTERVAL_SEC, IDLE_INTERVAL_SEC)
    while True:
        try:
            _, n_open = await asyncio.to_thread(run_check)
        except Exception as exc:
            log.warning("monitor tick failed: %s", exc)
            n_open = 0
        await asyncio.sleep(_sleep_for(n_open))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if len(sys.argv) >= 3 and sys.argv[1] == "--loop":
        run_loop(float(sys.argv[2]))
    else:
        sent, _ = run_check()
        print(f"monitor: {sent} alert(s) sent")
