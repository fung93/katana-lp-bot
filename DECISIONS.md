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
