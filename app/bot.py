"""Katana LP signal bot - Telegram entrypoint.

Signal-only: this process reads data and sends messages. It never signs a
transaction, moves funds, or touches a private key.

Locked to a single Telegram user (TELEGRAM_ALLOWED_USER_ID). Updates from any
other user never reach a handler (filtered at dispatch), and every handler
re-checks the id as defense in depth.

Commands:
    /ping   - health check
    /price  - current ETH price from pool slot0
    /pool   - price + Merkl campaign status (APR, daily KAT, end date)

    python -m app.bot
"""
from __future__ import annotations

import asyncio
import functools
import logging
from datetime import datetime, timezone

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, filters

from .chain import get_slot0
from .config import (
    get_allowed_user_id,
    get_pool_address,
    get_rpc_url,
    get_telegram_token,
)
from .merkl import fetch_campaign
from .rawlog import record
from .tickmath import tick_to_price

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
# httpx logs every request URL at INFO, and those URLs embed the bot token.
# Silence it so the token never lands in a log file.
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("katana-lp-bot")


def restricted(func):
    """Drop any update whose sender isn't the allowed user (defense in depth)."""

    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        allowed = context.application.bot_data["allowed_user_id"]
        user = update.effective_user
        if user is None or user.id != allowed:
            log.warning("Rejected %s from id=%s", func.__name__,
                        user.id if user else None)
            return
        return await func(update, context)

    return wrapper


@restricted
async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    await update.message.reply_text(
        f"\U0001f3d3 pong - Katana LP bot alive (signal-only)\n{now}"
    )


@restricted
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    rpc, pool_addr = get_rpc_url(), get_pool_address()
    try:
        slot0 = await asyncio.to_thread(get_slot0, rpc, pool_addr)
    except Exception as exc:
        await update.message.reply_text(f"⚠️ RPC read failed: {exc}")
        return
    px = tick_to_price(slot0.tick)
    record("price", tick=slot0.tick, price_usd=px)
    await update.message.reply_text(f"ETH price: ${px:,.2f}\ntick {slot0.tick}")


@restricted
async def pool(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    rpc, pool_addr = get_rpc_url(), get_pool_address()
    try:
        slot0 = await asyncio.to_thread(get_slot0, rpc, pool_addr)
    except Exception as exc:
        await update.message.reply_text(f"⚠️ RPC read failed: {exc}")
        return
    px = tick_to_price(slot0.tick)

    try:
        camp = await asyncio.to_thread(fetch_campaign)
    except Exception as exc:
        record("pool", tick=slot0.tick, price_usd=px, merkl_error=str(exc))
        await update.message.reply_text(
            f"ETH price: ${px:,.2f}  (tick {slot0.tick})\n"
            f"⚠️ Merkl campaign fetch failed: {exc}"
        )
        return

    days = camp.days_to_end()
    end_str = datetime.fromtimestamp(camp.end_ts, tz=timezone.utc).strftime(
        "%Y-%m-%d %H:%M UTC"
    )
    if camp.has_ended():
        expiry = "  ⚠️ ENDED"
    elif camp.is_expiring(7):
        expiry = "  ⚠️ ENDS SOON"
    else:
        expiry = ""
    record("pool", tick=slot0.tick, price_usd=px, apr_pct=camp.apr_pct,
           daily_reward=camp.daily_reward, daily_usd=camp.daily_usd, end_ts=camp.end_ts)
    await update.message.reply_text(
        "\U0001f4ca vbUSDC/vbETH 0.05%\n"
        f"ETH price: ${px:,.2f}  (tick {slot0.tick})\n"
        f"Incentive APR: {camp.apr_pct:.1f}%\n"
        f"Daily {camp.reward_symbol}: {camp.daily_reward:,.0f}  "
        f"(≈ ${camp.daily_usd:,.0f}/day)\n"
        f"Campaign ends: {end_str}  ({days:.1f} days){expiry}"
    )


def build_application() -> Application:
    token = get_telegram_token()
    allowed = get_allowed_user_id()
    app = Application.builder().token(token).build()
    app.bot_data["allowed_user_id"] = allowed
    only_me = filters.User(user_id=allowed)
    app.add_handler(CommandHandler("ping", ping, filters=only_me))
    app.add_handler(CommandHandler("price", price, filters=only_me))
    app.add_handler(CommandHandler("pool", pool, filters=only_me))
    log.info("Bot configured; locked to user id=%s", allowed)
    return app


def main() -> None:
    app = build_application()
    log.info("Starting long-polling...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
