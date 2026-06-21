"""Tests for the V3 composition math: round-trip, accumulation direction, edges."""
from __future__ import annotations

from app.liquidity import composition, liquidity_for_capital
from app.positions import bounds_to_ticks

LOW, UP = bounds_to_ticks(1600, 1800)  # lower_tick, upper_tick for a $1600-1800 band


def test_entry_value_matches_capital() -> None:
    L = liquidity_for_capital(5000, 1700, LOW, UP)
    usdc, eth = composition(1700, LOW, UP, L)
    assert abs((usdc + eth * 1700) - 5000) / 5000 < 0.001


def test_price_drop_accumulates_eth() -> None:
    L = liquidity_for_capital(5000, 1700, LOW, UP)
    _, eth_entry = composition(1700, LOW, UP, L)
    _, eth_lower = composition(1650, LOW, UP, L)
    assert eth_lower > eth_entry  # an LP buys ETH as the price falls


def test_all_eth_below_range() -> None:
    L = liquidity_for_capital(5000, 1700, LOW, UP)
    usdc, eth = composition(1500, LOW, UP, L)  # below the $1600 lower bound
    assert usdc < 1.0      # ~0 USDC left
    assert eth > 0


def test_all_usdc_above_range() -> None:
    L = liquidity_for_capital(5000, 1700, LOW, UP)
    usdc, eth = composition(1900, LOW, UP, L)  # above the $1800 upper bound
    assert eth < 1e-6      # ~0 ETH left
    assert usdc > 0


def test_value_drops_when_price_drops() -> None:
    L = liquidity_for_capital(5000, 1700, LOW, UP)
    usdc, eth = composition(1600, LOW, UP, L)
    assert usdc + eth * 1600 < 5000  # impermanent loss + price drift


def test_liquidity_share_rewards_concentration() -> None:
    from app.liquidity import liquidity_share
    from app.positions import bounds_to_ticks
    l_pool = 6.8e16
    wlt, wut = bounds_to_ticks(1500, 1900)
    tlt, tut = bounds_to_ticks(1690, 1750)
    wide = liquidity_share(1000, 1720, wlt, wut, l_pool)
    tight = liquidity_share(1000, 1720, tlt, tut, l_pool)
    assert tight > wide > 0      # same $, tighter range -> larger liquidity share
