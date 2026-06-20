"""Katana LP signal bot - Telegram entrypoint.

Signal-only: this process reads data and sends messages. It never signs a
transaction, moves funds, or touches a private key.

Locked to a single Telegram user (TELEGRAM_ALLOWED_USER_ID). Updates from any
other user never reach a handler (filtered at dispatch), and every command
re-checks the id as defense in depth.

Commands:
    /ping        health check
    /price       current ETH price from pool slot0
    /pool        price + Merkl campaign status (APR, daily KAT, end date)
    /positions   list open positions with in/out-of-range status
    /status      on-demand per-position risk: in/out, border distance, IL
    /open        guided: prompts entry -> lower -> upper -> capital -> eth -> usdc
    /close       auto exit price + V3 exit composition + value change;
                 /close <id> to pick when several are open
    /cancel      abort an /open in progress

A background monitor (app.monitor) runs in the same process and alerts on a
sustained out-of-range / back-in-range change (with IL) and campaign expiry.

    python -m app.bot
"""
from __future__ import annotations

import asyncio
import functools
import logging
import os
from datetime import datetime, timezone

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from .chain import get_slot0
from .cmdargs import opt_amount, parse_kwargs, to_amount
from .config import (
    get_allowed_user_id,
    get_pool_address,
    get_rpc_url,
    get_telegram_token,
    get_wallet_address,
)
from .merkl import fetch_campaign, fetch_pool_kat
from .monitor import monitor_loop
from .positions import (
    close_position,
    exit_report,
    find_open_by_prefix,
    il_at_price,
    list_open,
    open_position,
)
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


async def _read_price() -> tuple[int, float]:
    """(tick, USD price) from the pool's current slot0."""
    slot0 = await asyncio.to_thread(get_slot0, get_rpc_url(), get_pool_address())
    return slot0.tick, tick_to_price(slot0.tick)


# --------------------------------------------------------------------------- #
# Simple read commands
# --------------------------------------------------------------------------- #
@restricted
async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    await update.message.reply_text(
        f"\U0001f3d3 pong - Katana LP bot alive (signal-only)\n{now}"
    )


@restricted
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        tick, px = await _read_price()
    except Exception as exc:
        await update.message.reply_text(f"⚠️ RPC read failed: {exc}")
        return
    record("price", tick=tick, price_usd=px)
    await update.message.reply_text(f"ETH price: ${px:,.2f}\ntick {tick}")


@restricted
async def pool(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        tick, px = await _read_price()
    except Exception as exc:
        await update.message.reply_text(f"⚠️ RPC read failed: {exc}")
        return
    try:
        camp = await asyncio.to_thread(fetch_campaign)
    except Exception as exc:
        record("pool", tick=tick, price_usd=px, merkl_error=str(exc))
        await update.message.reply_text(
            f"ETH price: ${px:,.2f}  (tick {tick})\n"
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
    record("pool", tick=tick, price_usd=px, apr_pct=camp.apr_pct,
           daily_reward=camp.daily_reward, daily_usd=camp.daily_usd, end_ts=camp.end_ts)
    await update.message.reply_text(
        "\U0001f4ca vbUSDC/vbETH 0.05%\n"
        f"ETH price: ${px:,.2f}  (tick {tick})\n"
        f"Incentive APR: {camp.apr_pct:.1f}%\n"
        f"Daily {camp.reward_symbol}: {camp.daily_reward:,.0f}  "
        f"(≈ ${camp.daily_usd:,.0f}/day)\n"
        f"Campaign ends: {end_str}  ({days:.1f} days){expiry}"
    )


@restricted
async def positions_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        rows = await asyncio.to_thread(list_open)
    except Exception as exc:
        await update.message.reply_text(f"⚠️ DB error: {exc}")
        return
    if not rows:
        await update.message.reply_text("No open positions.")
        return
    try:
        cur_tick, cur_px = await _read_price()
        header = f"\U0001f4cb Open positions — current ETH ${cur_px:,.2f}\n"
    except Exception:
        cur_tick = None
        header = "\U0001f4cb Open positions — (current price read failed)\n"
    lines = []
    for p in rows:
        if cur_tick is None:
            status = "?"
        elif p.in_range(cur_tick):
            status = "✅ in range"
        else:
            status = "⚠️ OUT of range"
        lines.append(
            f"\n#{p.id[:8]}  {status}\n"
            f"  range ${p.price_low:,.0f}–${p.price_high:,.0f}"
            f" · entry ${p.entry_price:,.0f} · ${p.capital_usd:,.0f}"
            f" · {p.opened_at:%Y-%m-%d}"
        )
    await update.message.reply_text(header + "".join(lines))


# --------------------------------------------------------------------------- #
# /close  — auto exit price + V3 exit composition + value change (+ optional KAT)
# --------------------------------------------------------------------------- #
@restricted
async def close_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    prefix, kvs = None, args
    if args and "=" not in args[0]:           # leading token without '=' is an id
        prefix, kvs = args[0].lstrip("#"), args[1:]
    try:
        kw = parse_kwargs(kvs)
        exit_override = opt_amount(kw, "exit")   # optional manual exit price
        kat = opt_amount(kw, "kat")              # optional manual KAT, until wallet wired
    except ValueError as exc:
        await update.message.reply_text(f"⚠️ {exc}\nUsage: /close  (or)  /close <id>")
        return

    try:
        matches = (await asyncio.to_thread(find_open_by_prefix, prefix) if prefix
                   else await asyncio.to_thread(list_open))
    except Exception as exc:
        await update.message.reply_text(f"⚠️ DB error: {exc}")
        return
    if not matches:
        await update.message.reply_text("No open positions to close.")
        return
    if len(matches) > 1:
        ids = ", ".join(m.id[:8] for m in matches)
        await update.message.reply_text(
            f"{len(matches)} open positions: {ids}\nClose one with /close <id>"
        )
        return
    pos = matches[0]

    if exit_override is not None:
        exit_price, src = exit_override, "manual"
    else:
        try:
            _, exit_price = await _read_price()
            src = "auto"
        except Exception as exc:
            await update.message.reply_text(
                f"⚠️ couldn't read exit price: {exc}\nProvide it: /close exit=1750"
            )
            return

    try:
        rep = exit_report(pos, exit_price)
    except Exception as exc:
        await update.message.reply_text(f"⚠️ couldn't compute exit composition: {exc}")
        return

    # KAT earned: a manual kat= wins; else diff the wallet's pool KAT vs the open snapshot.
    wallet = get_wallet_address()
    kat_earned, kat_note = kat, None
    if kat_earned is None:
        if wallet is None:
            kat_note = "set WALLET_ADDRESS to auto-track"
        elif pos.kat_at_open is None:
            kat_note = "opened before KAT tracking"
        else:
            try:
                now_kat = await asyncio.to_thread(fetch_pool_kat, wallet, get_pool_address())
                kat_earned = max(0.0, now_kat - pos.kat_at_open)
            except Exception as exc:
                kat_note = f"Merkl read failed: {exc}"

    try:
        await asyncio.to_thread(
            close_position, pos.id, exit_price=exit_price, kat_earned=kat_earned)
    except Exception as exc:
        await update.message.reply_text(f"⚠️ {exc}")
        return
    record("close", position_id=pos.id, exit=exit_price, exit_src=src,
           eth_exit=rep.eth_exit, usdc_exit=rep.usdc_exit, entry_value=rep.entry_value,
           exit_value=rep.exit_value, delta=rep.delta, kat=kat_earned)

    delta_str = f"-${abs(rep.delta):,.2f}" if rep.delta < 0 else f"+${rep.delta:,.2f}"
    pct = (rep.delta / rep.entry_value * 100) if rep.entry_value else 0.0
    kat_line = f"{kat_earned:,.2f} KAT" if kat_earned is not None else f"— ({kat_note})"
    await update.message.reply_text(
        f"✅ Position #{pos.id[:8]} closed\n"
        f"1. Exit price: ${exit_price:,.2f} ({src})\n"
        f"2. Exit holdings: {rep.eth_exit:.4f} ETH + ${rep.usdc_exit:,.2f} USDC\n"
        f"3. Value: ${rep.entry_value:,.2f} → ${rep.exit_value:,.2f}"
        f"  ({delta_str}, {pct:+.1f}%)\n"
        f"4. KAT earned: {kat_line}"
    )


# --------------------------------------------------------------------------- #
# Guided /open conversation
# --------------------------------------------------------------------------- #
OPEN_STEP = 0

OPEN_FIELDS = [
    ("entry", "Entry price in USD? (e.g. 1700)"),
    ("lower", "Lower bound price in USD? (e.g. 1600)"),
    ("upper", "Upper bound price in USD? (e.g. 1800)"),
    ("capital", "Capital in USD? (e.g. 5000)"),
    ("eth", "ETH amount? (e.g. 1.5)"),
    ("usdc", "USDC amount? (e.g. 2500)"),
]


async def open_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["open"] = {"i": 0, "vals": {}}
    await update.message.reply_text(
        "New position (signal-only log).\n"
        f"{OPEN_FIELDS[0][1]}\n\nSend /cancel to abort."
    )
    return OPEN_STEP


async def open_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    st = context.user_data.get("open")
    if not st:
        return ConversationHandler.END
    i = st["i"]
    field, prompt = OPEN_FIELDS[i]
    try:
        st["vals"][field] = to_amount(update.message.text)
    except ValueError:
        await update.message.reply_text(f"Not a number — {prompt}")
        return OPEN_STEP
    st["i"] = i = i + 1
    if i < len(OPEN_FIELDS):
        await update.message.reply_text(OPEN_FIELDS[i][1])
        return OPEN_STEP

    v = st["vals"]
    context.user_data.pop("open", None)
    # Snapshot the wallet's cumulative pool KAT so /close can diff it later.
    kat_at_open = None
    wallet = get_wallet_address()
    if wallet:
        try:
            kat_at_open = await asyncio.to_thread(fetch_pool_kat, wallet, get_pool_address())
        except Exception:
            kat_at_open = None  # never block opening on a Merkl hiccup
    try:
        pos = await asyncio.to_thread(
            open_position, entry_price=v["entry"], lower_price=v["lower"],
            upper_price=v["upper"], capital_usd=v["capital"],
            amount_eth=v["eth"], amount_usdc=v["usdc"], kat_at_open=kat_at_open,
        )
    except Exception as exc:
        await update.message.reply_text(f"⚠️ DB error: {exc}")
        return ConversationHandler.END
    record("open", position_id=pos.id, entry=v["entry"], lower=v["lower"],
           upper=v["upper"], capital=v["capital"])
    await update.message.reply_text(
        "✅ Position opened\n"
        f"id: {pos.id[:8]}\n"
        f"entry: ${v['entry']:,.2f}\n"
        f"range: ${pos.price_low:,.2f} – ${pos.price_high:,.2f}\n"
        f"capital: ${v['capital']:,.2f}  ({v['eth']:g} ETH + {v['usdc']:g} USDC)"
    )
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("open", None)
    await update.message.reply_text("Cancelled.")
    return ConversationHandler.END


@restricted
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        rows = await asyncio.to_thread(list_open)
    except Exception as exc:
        await update.message.reply_text(f"⚠️ DB error: {exc}")
        return
    if not rows:
        await update.message.reply_text("No open positions.")
        return
    try:
        tick, px = await _read_price()
    except Exception as exc:
        await update.message.reply_text(f"⚠️ RPC read failed: {exc}")
        return
    out = [f"\U0001f4e1 Status — ETH ${px:,.2f}"]
    for p in rows:
        flag = "✅ in range" if p.in_range(tick) else "⚠️ OUT of range"
        il_usd, il_pct = il_at_price(p, px)
        dist = min(abs(px - p.price_low), abs(p.price_high - px)) / px * 100
        out.append(
            f"\n#{p.id[:8]}  {flag}\n"
            f"  range ${p.price_low:,.0f}–${p.price_high:,.0f}  (nearest border {dist:.1f}%)\n"
            f"  IL: -${abs(il_usd):,.2f} ({il_pct:+.1%})"
        )
    await update.message.reply_text("\n".join(out))


async def _post_init(application: Application) -> None:
    # Alerts run via GitHub Actions cron (python -m app.monitor). Start an
    # in-process loop only when explicitly asked (e.g. an always-on single host).
    if os.environ.get("INPROCESS_MONITOR") == "1":
        application.bot_data["_monitor_task"] = asyncio.create_task(monitor_loop())
        log.info("in-process monitor enabled")
    else:
        log.info("in-process monitor off (alerts run via GitHub Actions cron)")


def build_application() -> Application:
    token = get_telegram_token()
    allowed = get_allowed_user_id()
    app = Application.builder().token(token).post_init(_post_init).build()
    app.bot_data["allowed_user_id"] = allowed

    only_me = filters.User(user_id=allowed)
    text_me = filters.TEXT & ~filters.COMMAND & only_me

    app.add_handler(CommandHandler("ping", ping, filters=only_me))
    app.add_handler(CommandHandler("price", price, filters=only_me))
    app.add_handler(CommandHandler("pool", pool, filters=only_me))
    app.add_handler(CommandHandler("positions", positions_cmd, filters=only_me))
    app.add_handler(CommandHandler("status", status, filters=only_me))
    app.add_handler(CommandHandler("close", close_cmd, filters=only_me))
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("open", open_start, filters=only_me)],
        states={OPEN_STEP: [MessageHandler(text_me, open_step)]},
        fallbacks=[CommandHandler("cancel", cancel, filters=only_me)],
    ))
    log.info("Bot configured; locked to user id=%s", allowed)
    return app


def main() -> None:
    app = build_application()
    log.info("Starting long-polling...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
