-- Phase 3 cron: alert state persisted in Neon (a scheduled run has no memory
-- between invocations). monitor_state holds each position's sustained-range
-- hysteresis; monitor_meta holds small scheduler bookkeeping (e.g. the last
-- campaign-expiry alert date).
create table if not exists monitor_state (
    position_id uuid primary key references positions(id) on delete cascade,
    in_range    boolean not null,
    since       double precision not null,   -- epoch seconds the current state began
    alerted     boolean not null default false,
    alerted_out boolean not null default false,
    updated_at  timestamptz not null default now()
);

create table if not exists monitor_meta (
    key        text primary key,
    value      text not null,
    updated_at timestamptz not null default now()
);
