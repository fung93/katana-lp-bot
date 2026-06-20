-- KAT tracking: snapshot the wallet's cumulative pool KAT at open, so a
-- position's KAT earned = (pool KAT at close) - (pool KAT at open).
alter table positions add column if not exists kat_at_open numeric;
