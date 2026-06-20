# Katana LP Bot — Build Plan

**Pair:** vbUSDC–vbETH 0.05% (pool `0x2A2C512beAA8eB15495726C235472D82EFFB7A6B`)
**Merkl campaign:** `0xc186ab9ba208211ed853cd21a79fce531f299b8fa7850417c407b19f80c0a030`
**Type:** signal + position tracker (no automated execution)
**Stack:** new repo · new Neon project · Telegram · Katana data
**Chain ID:** 747474

---

## Governing principle

The only number that matters is **net P&L = fees + KAT − realized IL − gas − funding**.
Every position record and every alert is built around that figure. Headline APR is ignored on its own.

## Data-source rule

- **Interactive commands** (human triggers): Katana MCP is fine — agent-in-the-loop is acceptable.
- **Autonomous monitoring loop** (24/7, no human): read directly. Pool `slot0` via RPC for the live tick; Merkl public API (`api.merkl.xyz` — confirm exact v4 opportunities path before coding) for campaign APR + end date. Do **not** route the polling loop through MCP.

---

## Phase 0 — Scaffold

- New GitHub repo, new Neon project, Telegram bot token, `.env`
- Pick stack (recommend reusing the perps bot's language so tooling carries over) — record the decision in the repo, don't leave it implicit
- `/ping` health-check command
- DB schema v0: `positions`, `position_events` tables (sketch below)
- Wire RPC endpoint + confirm `slot0` read returns the current tick for the pool

**Exit criteria:** bot responds to `/ping`; can read live ETH price from `slot0` once.

## Phase 1 — Read-only monitoring

- `/price` → current ETH price (RPC `slot0`, fall back to MCP `get_token_prices`)
- `/pool` → current tick, active range, pool APR, daily KAT, **campaign end date**
- Merkl fetch: surface APR breakdown + expiry; flag if campaign ends within N days
- No DB writes yet beyond a raw log

**Exit criteria:** you can ask the bot for price + live campaign status and trust the numbers.

## Phase 2 — Position logging

- `/open` → manual entry: entry price, lower/upper bound (price or tick), capital, token amounts, timestamp
- `/close` → exit price, fees earned, KAT earned, gas paid
- `/positions` → list open positions with current in/out-of-range status
- Writes to `positions` + `position_events`

**Exit criteria:** full open→close lifecycle captured in Neon from Telegram input.

## Phase 3 — Border & IL alerts ★ core value

- Monitoring loop every N minutes (direct RPC, not MCP)
- Per open position compute: distance-to-nearest-border (%), in/out-of-range, IL-at-current-price, IL-at-border (closed form)
- Net P&L estimate = accrued fees + KAT − IL − gas
- Telegram alert when: within threshold of a border, **or** net P&L crosses a set level
- **Hysteresis band** so a price hovering at the edge doesn't spam you

**Exit criteria:** bot proactively warns before a position drifts out of range, with the IL number attached.

## Phase 4 — Range suggester

- Realized-vol estimate from recent ETH price history
- Width-from-vol model: set width so expected time-in-range ≈ target (e.g. 80%)
- Expected daily KAT for a proposed range = (your liquidity share) × (pool daily KAT) × (expected time-in-range)
- `/suggest` → proposed lower/upper + expected daily KAT + expected time-in-range

**Exit criteria:** `/suggest` returns a defensible range with an honest reward estimate, not just the headline APR.

## Phase 5 — Position analytics (feedback loop)

- Per-closed-position metrics: net APR, time-in-range %, realized IL, fees, KAT
- Aggregate queries: performance grouped by width and by volatility regime
- `/stats` → what range width / market condition actually paid off

> **Framing note:** this is a heuristic feedback loop over your own history, not ML.
> At a handful of positions, a model overfits noise. Once you have dozens of closed
> positions, a simple fit becomes worth revisiting. Don't call it self-learning until it is.

## Phase 6 — Delta-neutral hedge (optional, high leverage)

- Integrate Katana Perps (reuse perps bot infra)
- Size a short ETH perp to the position's ETH delta → neutralizes directional IL
- Delta-rebalance triggers as price moves through the range
- Funding-rate awareness; net P&L now subtracts funding

**Exit criteria:** IL on the directional ETH exposure is hedged; you're earning fees + KAT minus funding.

---

## Cross-cutting (build in from Phase 0)

- **Net P&L accounting** — every record carries the full formula, never APR alone
- **Campaign-expiry awareness** — alert before the Merkl campaign lapses (APR ~43% → ~2% overnight when it ends)
- **Backtest harness** — reuse the quant lab loop to simulate range strategies on historical ETH price before risking capital

---

## DB schema v0 (sketch)

```
positions
  id              uuid pk
  status          text        -- open | closed
  entry_price     numeric
  lower_bound     numeric     -- price or tick
  upper_bound     numeric
  capital_usd     numeric
  amount_eth      numeric
  amount_usdc     numeric
  opened_at       timestamptz
  closed_at       timestamptz null

position_events
  id              uuid pk
  position_id     uuid fk
  kind            text        -- open | close | alert | claim | rebalance
  price           numeric
  fees_earned     numeric null
  kat_earned      numeric null
  gas_paid        numeric null
  il_realized     numeric null
  note            text null
  created_at      timestamptz
```

---

## Open decisions before Phase 0

1. Language/stack — reuse perps bot's, or fresh?
2. Is the Phase 6 hedge in scope for v1, or explicitly deferred?
3. Confirm the exact Merkl v4 API endpoint for opportunities on chain 747474.
