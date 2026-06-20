# Katana LP Bot

Signal-only LP position tracker for the Katana **vbUSDC/vbETH 0.05%** pool
(`0x2A2C512beAA8eB15495726C235472D82EFFB7A6B`, chain 747474).

**Signal-only.** It reads on-chain/market data and sends Telegram messages. It
never executes trades, never moves funds, and never handles private keys.

See [`lp_bot_build_plan.md`](lp_bot_build_plan.md) for the full roadmap and
[`DECISIONS.md`](DECISIONS.md) for stack/hosting decisions. **This repo currently
implements Phase 0 only.**

## Layout

```
app/
  config.py       env loading (secrets from .env; never printed)
  tickmath.py     tick <-> USD-price conversion (the price boundary; full derivation inside)
  chain.py        read-only JSON-RPC slot0() read (no web3.py)
  db.py           psycopg v3 + Neon cold-start retry
  migrate.py      forward-only SQL migration runner  ->  python -m app.migrate
  bot.py          Telegram bot, /ping, single-user lock  ->  python -m app.bot
  check_slot0.py  one-shot live ETH price print  ->  python -m app.check_slot0
migrations/
  0001_init.sql   positions + position_events (bounds are INTEGER TICKS)
tests/
  test_tickmath.py  round-trip price->tick->price
```

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows;  source .venv/bin/activate on *nix
pip install -r requirements-dev.txt
cp .env.example .env            # then fill in your secrets
```

All secrets live in `.env` (gitignored). The bot is locked to your Telegram user
id via `TELEGRAM_ALLOWED_USER_ID`; everyone else is ignored.

## Run

```bash
python -m pytest                # tick-math round-trip test (no secrets needed)
python -m app.migrate           # apply schema to Neon (needs DATABASE_URL)
python -m app.check_slot0       # print live ETH price once (needs RPC_URL)
python -m app.bot               # start the Telegram bot (needs token + user id)
```

## Phase 0 exit criteria

- [x] `/ping` health-check command (single-user locked)
- [x] DB schema v0 (`positions`, `position_events`); bounds as INTEGER TICKS;
      `pool_address` + `fee_tier` added
- [x] tick <-> price helper, both directions, tested (round-trip < 0.1%)
- [x] read live `slot0` and print the ETH price via the tick->price helper

Live steps (migrate / slot0 / `/ping`) need the corresponding secret in `.env`.
