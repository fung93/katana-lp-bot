"""Phase 3 monitoring loop: proactive border / IL alerts.

Runs as an asyncio task inside the bot process (no extra dependency). Every
MONITOR_INTERVAL_SEC it reads the pool's live tick directly via RPC and checks
each open position. Alerts fire on a SUSTAINED state change (default 5 min) so a
price flickering across the border doesn't spam you:

  * out of range for >= sustain   -> "out of range" alert (with IL attached)
  * back in range for >= sustain  -> "back in range" alert (only after an out)

Plus a once-a-day Merkl campaign-expiry warning while you hold a position.

Hysteresis state is in memory: a restart re-establishes the baseline, so at worst
you get one repeat alert after a restart.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timezone

from .chain import get_slot0
from .config import get_pool_address, get_rpc_url
from .merkl import fetch_campaign
from .positions import il_at_price, list_open
from .tickmath import tick_to_price

log = logging.getLogger("katana-lp-bot.monitor")

MONITOR_INTERVAL_SEC = int(os.environ.get("MONITOR_INTERVAL_SEC", "60"))
RANGE_SUSTAIN_SEC = int(os.environ.get("RANGE_SUSTAIN_SEC", "300"))  # 5 minutes
EXPIRY_THRESHOLD_DAYS = 7


def step(state: dict | None, in_range: bool, now: float,
         sustain: float) -> tuple[dict, str | None]:
    """Advance one position's alert state.

    Returns (new_state, alert) where alert is:
      'out' - sustained out of range (always actionable),
      'in'  - sustained recovery (only after a prior 'out'),
      None  - nothing to send this tick.

    A state change resets the timer; an alert fires once the same state has held
    for `sustain` seconds. The 'in' alert is gated on a prior 'out' so a position
    that was simply in range the whole time never produces a "back in range".
    """
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


def _out_alert(p, price: float) -> str:
    il_usd, il_pct = il_at_price(p, price)
    return (f"⚠️ Position #{p.id[:8]} OUT of range (>{RANGE_SUSTAIN_SEC // 60} min)\n"
            f"ETH ${price:,.2f}  ·  range ${p.price_low:,.0f}–${p.price_high:,.0f}\n"
            f"IL now: -${abs(il_usd):,.2f} ({il_pct:+.1%})")


def _in_alert(p, price: float) -> str:
    return (f"✅ Position #{p.id[:8]} back IN range\n"
            f"ETH ${price:,.2f}  ·  range ${p.price_low:,.0f}–${p.price_high:,.0f}")


async def _tick(app, chat_id: int, state: dict, expiry_state: dict) -> None:
    positions = await asyncio.to_thread(list_open)
    if not positions:
        state.clear()
        return
    slot0 = await asyncio.to_thread(get_slot0, get_rpc_url(), get_pool_address())
    price = tick_to_price(slot0.tick)
    now = time.time()

    live = set()
    for p in positions:
        live.add(p.id)
        new_state, alert = step(state.get(p.id), p.in_range(slot0.tick), now,
                                RANGE_SUSTAIN_SEC)
        state[p.id] = new_state
        if alert == "out":
            await app.bot.send_message(chat_id, _out_alert(p, price))
            log.info("OUT alert sent for %s", p.id[:8])
        elif alert == "in":
            await app.bot.send_message(chat_id, _in_alert(p, price))
            log.info("IN alert sent for %s", p.id[:8])
    for pid in list(state):
        if pid not in live:
            del state[pid]

    await _maybe_expiry_alert(app, chat_id, expiry_state)


async def _maybe_expiry_alert(app, chat_id: int, expiry_state: dict) -> None:
    today = datetime.now(timezone.utc).date().isoformat()
    if expiry_state.get("date") == today:
        return
    expiry_state["date"] = today
    try:
        camp = await asyncio.to_thread(fetch_campaign)
    except Exception:
        return
    if camp.is_expiring(EXPIRY_THRESHOLD_DAYS):
        end = datetime.fromtimestamp(camp.end_ts, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M UTC")
        await app.bot.send_message(
            chat_id,
            f"⏳ Merkl campaign ends in {camp.days_to_end():.1f} days ({end}).\n"
            f"Incentive APR {camp.apr_pct:.1f}% drops to ~0 when it lapses.")


async def monitor_loop(app) -> None:
    chat_id = app.bot_data["allowed_user_id"]
    state: dict = {}
    expiry_state: dict = {}
    log.info("monitor loop started (interval %ss, sustain %ss)",
             MONITOR_INTERVAL_SEC, RANGE_SUSTAIN_SEC)
    while True:
        try:
            await _tick(app, chat_id, state, expiry_state)
        except Exception as exc:  # a bad tick must never kill the loop
            log.warning("monitor tick failed: %s", exc)
        await asyncio.sleep(MONITOR_INTERVAL_SEC)
