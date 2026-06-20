# Decisions log

Recorded per the build plan ("record the decision in the repo, don't leave it
implicit").

## D1 - Stack: Python 3.12 (runs on >=3.11), psycopg v3, Neon
Match the existing perps bot so tooling carries over: db.py pattern (pooled Neon
connection string + cold-start retry), SQL-file migration convention, secrets in
a gitignored `.env`.

## D2 - Telegram library: python-telegram-bot v21 (not aiogram)
Most mature/best-documented async option. `filters.User(ALLOWED_USER_ID)` makes
the single-user lock a one-liner at dispatch; `ConversationHandler` will cover
the multi-step `/open` dialog in Phase 2 without a new dependency. aiogram's main
edge (built-in FSM) doesn't justify the less-trodden path for a single-user bot.

## D3 - No web3.py (yet)
A `slot0()` read is one `eth_call`, encoded/decoded by hand in `app/chain.py`
over `httpx`. Avoids a heavy dependency. Revisit if later phases need broad ABI
coverage.

## D4 - Hosting: long-polling, host-agnostic; recommend Fly.io
Long-polling means no public URL/webhook to secure; the same process runs locally
and in the cloud.
- Recommended: Fly.io, one always-on 256 MB machine (`auto_stop_machines=false`),
  deployed via Dockerfile. ~$0-2/mo.
- $0-forever alternative: Oracle Cloud Always-Free ARM VM + a systemd unit.
- Avoid: Render free tier (sleeps after 15 min idle), Cloud Run (scale-to-zero
  fights long-polling), GitHub Actions cron (can't handle inbound commands).
- Deploy files are intentionally NOT in Phase 0; added after Phase 0 sign-off.

## D5 - Schema v0 corrections (vs the plan's sketch)
- `lower_bound` / `upper_bound` are INTEGER TICKS (tickLower/tickUpper), not prices.
- Added `pool_address` and `fee_tier` to `positions`.
- Prices the human sees are always derived from ticks via `app/tickmath.py`.

## D6 - Phase 2: position-logging UX + KAT attribution
- `/open` is a guided conversation (one prompt per field); `/close` is one-tap. All
  bounds are entered/shown in USD and stored as ticks (min/max guards the price->tick
  inversion, since token0 is the stablecoin).
- `/close` reports exit price (auto from `slot0`), V3 exit composition (ETH/USDC),
  entry->exit value change, and per-position KAT. Fees and gas were dropped on request:
  a signal-only bot with manually-logged positions cannot see on-chain fees or the gas
  of a tx it never signs.
- Liquidity is anchored on the declared capital (entry value == capital), which sidesteps
  any inconsistency in the manually entered token split. See `app/liquidity.py`.
- KAT attribution matches the POOL ADDRESS in the Merkl breakdown `reason`, NOT a single
  campaign id — the same pool runs many campaign ids over time. Per-position KAT = the
  wallet's pool-KAT snapshot at close minus at open (`kat_at_open`, migration 0002),
  endpoint `GET /v4/users/{wallet}/rewards?chainId=747474`.
- `WALLET_ADDRESS` (public, optional) in `.env` enables KAT tracking; absent it, `/close`
  shows the other three items and notes KAT is off.

## D7 - Phase 3: monitoring loop + sustained alerts
- The loop is an `asyncio` task inside the bot process (no APScheduler/cron), reading pool
  `slot0` directly via RPC every 60s. Started in `Application` post_init via
  `asyncio.create_task` with a retained reference (avoids PTB's `create_task` warning and
  the task being garbage-collected).
- Headline alert (user's spec): SUSTAINED out-of-range >= 5 min -> alert with IL attached;
  SUSTAINED back-in-range -> alert, but only after a prior "out" (a position that was in
  range the whole time never produces a "back in range"). A flicker below the sustain
  window is silent. Logic is `app/monitor.py:step()`, unit-tested with simulated timestamps.
- Hysteresis state is in memory; a restart re-baselines (at worst one repeat alert).
- Plus `/status` (on-demand risk readout) and a once-daily campaign-expiry warning while a
  position is open. Tunable via env `MONITOR_INTERVAL_SEC` (60) and `RANGE_SUSTAIN_SEC` (300).
- IL is computed vs HODL from the same V3 composition math; net P&L is shown as KAT - IL
  (fees/gas remain out of scope for a signal-only bot).
