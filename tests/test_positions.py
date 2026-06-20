"""Offline tests for the position USD<->tick boundary and arg parsing.

The DB functions (open/close/list) are exercised live against Neon, not here;
these cover the pure logic that's easy to get subtly wrong (the price->tick
inversion and the command parsing).
"""
from __future__ import annotations

import datetime as dt

import pytest

from app.cmdargs import amount_or_skip, opt_amount, parse_kwargs, req_amount, to_amount
from app.positions import Position, bounds_to_ticks, il_at_price
from app.tickmath import price_to_tick


def _pos(lower_tick: int, upper_tick: int, **kw) -> Position:
    base = dict(
        id="x", status="open", pool_address="0x", fee_tier=500, entry_price=1700.0,
        lower_tick=lower_tick, upper_tick=upper_tick, capital_usd=5000.0,
        amount_eth=1.5, amount_usdc=2500.0,
        opened_at=dt.datetime.now(dt.timezone.utc), closed_at=None,
    )
    base.update(kw)
    return Position(**base)


def test_bounds_to_ticks_orders_low_high() -> None:
    lt, ut = bounds_to_ticks(1600, 1800)
    assert lt < ut
    assert bounds_to_ticks(1800, 1600) == (lt, ut)  # input order must not matter


def test_price_bounds_roundtrip_to_usd() -> None:
    lt, ut = bounds_to_ticks(1600, 1800)
    p = _pos(lt, ut)
    assert abs(p.price_low - 1600) / 1600 < 0.001
    assert abs(p.price_high - 1800) / 1800 < 0.001
    assert p.price_low < p.price_high


def test_in_range_uses_current_tick() -> None:
    lt, ut = bounds_to_ticks(1600, 1800)
    p = _pos(lt, ut)
    assert p.in_range(price_to_tick(1700))        # inside the band
    assert not p.in_range(price_to_tick(1500))    # below $1600
    assert not p.in_range(price_to_tick(1900))    # above $1800


def test_parse_kwargs_and_amounts() -> None:
    kw = parse_kwargs(["entry=1700", "lower=$1,600", "upper=1800"])
    assert kw == {"entry": "1700", "lower": "$1,600", "upper": "1800"}
    assert req_amount(kw, "lower") == 1600.0      # $ and , stripped
    assert req_amount(kw, "entry") == 1700.0
    assert opt_amount(kw, "missing") is None


def test_parse_errors() -> None:
    with pytest.raises(ValueError):
        parse_kwargs(["noequals"])
    with pytest.raises(ValueError):
        req_amount({"x": "abc"}, "x")
    with pytest.raises(ValueError):
        req_amount({}, "entry")


def test_to_amount_and_skip() -> None:
    assert to_amount("$1,750.50") == 1750.50
    assert amount_or_skip("skip") is None
    assert amount_or_skip("-") is None
    assert amount_or_skip("") is None
    assert amount_or_skip("500") == 500.0
    with pytest.raises(ValueError):
        to_amount("abc")


def test_il_zero_at_entry_negative_away() -> None:
    lt, ut = bounds_to_ticks(1600, 1800)
    p = _pos(lt, ut)  # entry 1700, capital 5000
    il0, _ = il_at_price(p, 1700.0)
    assert abs(il0) < 1.0          # ~0 at entry (LP == HODL)
    il1, pct1 = il_at_price(p, 1780.0)
    assert il1 < 0 and pct1 < 0    # a move away is a loss vs HODL
