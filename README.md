# Katana LP Bot

Signal-only LP position tracker for the Katana **vbUSDC/vbETH 0.05%** pool
(`0x2A2C512beAA8eB15495726C235472D82EFFB7A6B`, chain 747474).

**Signal-only.** It reads on-chain/market data and sends Telegram messages. It
never executes trades, never moves funds, and never handles private keys.

See [`lp_bot_build_plan.md`](lp_bot_build_plan.md) for the full roadmap and
[`DECISIONS.md`](DECISIONS.md) for stack/hosting decisions. **This repo implements Phases 0–3 (scaffold, monitoring, position logging, border/IL alerts).**

## Layout

```
app/
  config.py       env loading (secrets from .env; never printed)
  tickmath.py     tick <-> USD-price conversion (the price boundary; full derivation inside)
  liquidity.py    V3 composition math (exit ETH/USDC + entry->exit value change)
  chain.py        read-only JSON-RPC slot0() read (no web3.py)
  merkl.py        read-only Merkl v4 client (campaign status + per-wallet pool KAT)
  rawlog.py       append-only JSONL log of fetches (data/, gitignored)
  cmdargs.py      tiny parsers for command input
  db.py           psycopg v3 + Neon cold-start retry
  positions.py    open/close/list positions + exit report + IL (USD in, ticks stored)
  monitor.py      background loop: sustained out/in-range + campaign-expiry alerts
  migrate.py      forward-only SQL migration runner  ->  python -m app.migrate
  bot.py          Telegram bot (/ping /price /pool /positions /status /open /close)  ->  python -m app.bot
  check_slot0.py  one-shot live ETH price print  ->  python -m app.check_slot0
migrations/
  0001_init.sql           positions + position_events (bounds are INTEGER TICKS)
  0002_kat_at_open.sql    per-position KAT snapshot column
  0003_monitor_state.sql  alert hysteresis state for the scheduled monitor
tests/
  test_tickmath.py   round-trip price->tick->price
  test_merkl.py      campaign parsing + expiry logic (offline)
  test_positions.py  USD<->tick bounds + arg parsing + IL
  test_liquidity.py  V3 composition (round-trip + edges)
  test_monitor.py    sustained in/out-of-range alert state machine
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

## Commands (in Telegram, locked to you)

- `/ping` — health check
- `/price` — current ETH price from pool `slot0`
- `/pool` — price + Merkl campaign status (incentive APR, daily KAT, end date; ⚠️ flagged if it ends within 7 days)
- `/positions` — open positions with in/out-of-range status
- `/status` — on-demand per-position risk: in/out, distance to nearest border, IL
- `/open` — guided prompts (entry → lower → upper → eth → usdc); value is computed as eth×entry + usdc; USD in, ticks stored
- `/close` — auto exit price + V3 exit composition + entry→exit value change + per-position KAT
- `/cancel` — abort an `/open` in progress

A **monitor** check (`python -m app.monitor`) alerts on a **sustained** out-of-range
(≥5 min, with IL attached) and back-in-range change, plus a once-daily campaign-expiry
warning. In production it runs as a scheduled job (see Deploy); run it in-process instead
with `INPROCESS_MONITOR=1`. Tunable via `MONITOR_INTERVAL_SEC` / `RANGE_SUSTAIN_SEC`.

## Deploy — alerts 24/7 via GitHub Actions (no server)

The alerts are outbound-only, so they run as a scheduled job rather than an always-on host:

- [`.github/workflows/monitor.yml`](.github/workflows/monitor.yml) runs `python -m app.monitor`
  every 5 min — **free on a public repo** (private repos cap Actions minutes).
- Add repo **secrets** (Settings → Secrets and variables → Actions): `TELEGRAM_BOT_TOKEN`,
  `TELEGRAM_ALLOWED_USER_ID`, `DATABASE_URL`, `RPC_URL`, `WALLET_ADDRESS`.
- Alert hysteresis state lives in Neon (`monitor_state`), so it survives between runs.
- Run the **commands** (`/open`, `/close`, `/status`, …) locally on demand: `python -m app.bot`.
- Note: a 5-min cron keeps Neon fairly active; if you near Neon's free compute limit, lower
  Neon's autosuspend (~1 min) or widen the cron interval.

## Phase 0 exit criteria

- [x] `/ping` health-check command (single-user locked)
- [x] DB schema v0 (`positions`, `position_events`); bounds as INTEGER TICKS;
      `pool_address` + `fee_tier` added
- [x] tick <-> price helper, both directions, tested (round-trip < 0.1%)
- [x] read live `slot0` and print the ETH price via the tick->price helper

Live steps (migrate / slot0 / `/ping`) need the corresponding secret in `.env`.

## Phase 1 exit criteria

- [x] `/price` — live ETH price from `slot0`
- [x] `/pool` — live tick/price + Merkl incentive APR, daily KAT, campaign end date, flagged when ending within 7 days
- [x] Merkl v4 client (`GET /v4/campaigns?campaignId=`); parsing + expiry logic tested offline
- [x] raw fetch log (`data/raw_log.jsonl`); no position writes yet

Not in scope until later: monitoring loop + alerts (Phase 3).

## Phase 2 exit criteria

- [x] `/open` (guided), `/close`, `/positions` — full open→close lifecycle from Telegram
- [x] writes to `positions` + `position_events` in Neon; bounds stored as ticks, USD at the boundary
- [x] `/close` reports exit price, exit ETH/USDC, entry→exit value change, KAT earned
- [x] per-position KAT via Merkl per-wallet pool attribution (snapshot at open, diff at close)

## Phase 3 exit criteria

- [x] background monitor loop (60s, direct RPC) inside the bot process — no extra deps
- [x] **sustained** out-of-range (≥5 min) alert with IL attached; back-in-range recovery alert
- [x] flicker below the sustain window stays silent (state machine unit-tested)
- [x] `/status` on-demand risk readout; once-daily campaign-expiry warning
- [x] proven end-to-end: a real out-of-range alert reached Telegram in the live test

Not in scope until later: range suggester (Phase 4), analytics (Phase 5), hedge (Phase 6).
