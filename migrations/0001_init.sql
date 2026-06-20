-- Phase 0 schema v0 for the Katana LP signal bot.
--
-- Bounds are INTEGER TICKS (Uniswap V3), not prices. Any price shown to the
-- human is derived from a tick via app/tickmath.py. All *_price / *_usd columns
-- hold human USD values (USDC per 1 ETH for prices).

create extension if not exists pgcrypto;  -- gen_random_uuid() on any PG version

create table if not exists positions (
    id            uuid primary key default gen_random_uuid(),
    status        text not null default 'open' check (status in ('open', 'closed')),
    pool_address  text not null,                 -- which pool this position is in
    fee_tier      integer not null,              -- Uniswap fee units: 500 = 0.05%
    entry_price   numeric,                       -- USD/ETH at entry (human)
    -- Uniswap tick range. lower_bound = tickLower, upper_bound = tickUpper,
    -- and lower_bound < upper_bound (enforced below).
    -- NOTE: token0 is the stablecoin, so ETH price DECREASES as tick increases.
    -- Therefore tickLower (lower_bound) is the HIGHER ETH price and tickUpper
    -- (upper_bound) is the LOWER ETH price. Keep this straight in Phase 2.
    lower_bound   integer not null,              -- INTEGER TICK (tickLower)
    upper_bound   integer not null,              -- INTEGER TICK (tickUpper)
    capital_usd   numeric,
    amount_eth    numeric,
    amount_usdc   numeric,
    opened_at     timestamptz not null default now(),
    closed_at     timestamptz,
    check (upper_bound > lower_bound)
);

create table if not exists position_events (
    id           uuid primary key default gen_random_uuid(),
    position_id  uuid not null references positions(id) on delete cascade,
    kind         text not null
                 check (kind in ('open', 'close', 'alert', 'claim', 'rebalance')),
    price        numeric,                        -- USD/ETH at the event (human)
    fees_earned  numeric,
    kat_earned   numeric,
    gas_paid     numeric,
    il_realized  numeric,
    note         text,
    created_at   timestamptz not null default now()
);

create index if not exists idx_positions_status
    on positions (status);
create index if not exists idx_position_events_position_id
    on position_events (position_id);
