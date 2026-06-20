"""Environment configuration for the Katana LP signal bot.

Secrets are read from the process environment, populated from a gitignored
``.env`` file. Values are never printed or logged. Each accessor requires only
the variables its caller needs, so a single entrypoint (e.g. the live slot0
read) can run with just its own secret set.
"""
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()  # load .env if present; a no-op when env vars are set directly

# Pool facts for vbUSDC/vbETH 0.05% on Katana (chain 747474).
POOL_ADDRESS_DEFAULT = "0x2A2C512beAA8eB15495726C235472D82EFFB7A6B"
CHAIN_ID = 747474


class ConfigError(RuntimeError):
    """Raised when a required environment variable is missing or malformed."""


def _require(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise ConfigError(
            f"Missing required environment variable: {name}. See .env.example."
        )
    return val


def get_rpc_url() -> str:
    return _require("RPC_URL")


def get_pool_address() -> str:
    return os.environ.get("POOL_ADDRESS", POOL_ADDRESS_DEFAULT)


def get_database_url() -> str:
    return _require("DATABASE_URL")


def get_telegram_token() -> str:
    return _require("TELEGRAM_BOT_TOKEN")


def get_allowed_user_id() -> int:
    raw = _require("TELEGRAM_ALLOWED_USER_ID")
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(
            "TELEGRAM_ALLOWED_USER_ID must be an integer (your numeric Telegram user ID)."
        ) from exc
