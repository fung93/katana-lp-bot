"""Katana LP signal bot - Telegram entrypoint.

Signal-only: this process reads data and sends messages. It never signs a
transaction, moves funds, or touches a private key.

Locked to a single Telegram user (TELEGRAM_ALLOWED_USER_ID). Updates from any
other user never reach a handler (filtered at dispatch), and each handler
re-checks the id as defense in depth.

    python -m app.bot
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, filters

from .config import get_allowed_user_id, get_telegram_token

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
# httpx logs every request URL at INFO, and those URLs embed the bot token.
# Silence it so the token never lands in a log file.
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("katana-lp-bot")


async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    allowed = context.application.bot_data["allowed_user_id"]
    user = update.effective_user
    if user is None or user.id != allowed:  # defense in depth; dispatch already filters
        log.warning("Rejected /ping from unauthorized user id=%s",
                    user.id if user else None)
        return
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    await update.message.reply_text(
        f"\U0001f3d3 pong - Katana LP bot alive (signal-only)\n{now}"
    )


def build_application() -> Application:
    token = get_telegram_token()
    allowed = get_allowed_user_id()
    app = Application.builder().token(token).build()
    app.bot_data["allowed_user_id"] = allowed
    # Only the allowed user's commands ever reach a handler.
    app.add_handler(CommandHandler("ping", ping, filters=filters.User(user_id=allowed)))
    log.info("Bot configured; locked to user id=%s", allowed)
    return app


def main() -> None:
    app = build_application()
    log.info("Starting long-polling...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
