"""Round-trip and anchor tests for the tick <-> price helper.

These tests use only the standard library plus the helper under test, so they
run without any network, database, or secrets.
"""
from __future__ import annotations

import math

import pytest

from app.tickmath import (
    TICK_SPACING,
    align_to_spacing,
    price_to_tick,
    tick_to_price,
)

# A spread of realistic ETH prices around the ~$1700 working point.
PRICES = [1200.0, 1500.0, 1708.0, 2000.0, 2500.0, 3000.0, 4000.0]


@pytest.mark.parametrize("price", PRICES)
def test_round_trip_within_one_spacing(price: float) -> None:
    tick = price_to_tick(price)
    assert tick % TICK_SPACING == 0, f"{tick} is not a valid tick"
    back = tick_to_price(tick)
    rel = abs(back - price) / price
    # One tick spacing ~= 0.10%; snapping to the nearest is at most ~half that.
    assert rel < 0.001, f"{price} -> {tick} -> {back:.4f} (rel error {rel:.5%})"


def test_price_decreases_as_tick_increases() -> None:
    # token0 is the stablecoin, so a higher tick is a cheaper ETH.
    assert tick_to_price(201_800) > tick_to_price(201_900)


def test_known_anchor_1708() -> None:
    tick = price_to_tick(1708.0)
    assert 201_700 <= tick <= 202_000, f"unexpected tick {tick} for $1708"
    assert math.isclose(tick_to_price(tick), 1708.0, rel_tol=0.001)


def test_align_to_spacing_rounds_to_nearest_ten() -> None:
    assert align_to_spacing(201_894) == 201_890
    assert align_to_spacing(201_895) == 201_900
    assert align_to_spacing(-201_894) == -201_890


def test_rejects_nonpositive_price() -> None:
    with pytest.raises(ValueError):
        price_to_tick(0)
    with pytest.raises(ValueError):
        price_to_tick(-100)


if __name__ == "__main__":  # allow `python tests/test_tickmath.py` without pytest
    for p in PRICES:
        t = price_to_tick(p)
        b = tick_to_price(t)
        print(f"${p:>8,.2f}  ->  tick {t:>7d}  ->  ${b:>9,.4f}   "
              f"(rel {abs(b - p) / p:.5%})")
