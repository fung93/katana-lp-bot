"""Offline tests for the vol/realized-vol and range-suggester logic (seeded MC)."""
from __future__ import annotations

from app.prices import hourly_vol
from app.suggest import (
    _sim_logprices,
    _time_in_range,
    suggest_range,
    time_in_range_for_bounds,
)


def test_hourly_vol_flat_and_known() -> None:
    assert hourly_vol([100, 100, 100, 100]) == 0.0
    assert hourly_vol([100, 110, 100, 110]) > 0.0


def test_time_in_range_monotonic_in_width() -> None:
    vals = _sim_logprices(0.01, 24, 800, seed=1)
    narrow = _time_in_range(vals, 0.01)
    wide = _time_in_range(vals, 0.10)
    assert 0.0 <= narrow < wide <= 1.0


def test_suggest_hits_target() -> None:
    s = suggest_range(1700, 0.0066, days=7, target_tir=0.80, n_paths=1500, seed=7)
    assert 0.76 <= s.time_in_range <= 0.84          # close to the 80% target
    assert s.lower_price < 1700 < s.upper_price
    assert s.half_width_pct > 0


def test_higher_vol_gives_wider_range() -> None:
    calm = suggest_range(1700, 0.004, days=7, target_tir=0.80, seed=3)
    wild = suggest_range(1700, 0.010, days=7, target_tir=0.80, seed=3)
    assert wild.half_width_pct > calm.half_width_pct


def test_lower_target_gives_narrower_range() -> None:
    loose = suggest_range(1700, 0.0066, days=7, target_tir=0.60, seed=5)
    tight = suggest_range(1700, 0.0066, days=7, target_tir=0.90, seed=5)
    assert tight.half_width_pct > loose.half_width_pct   # higher TIR needs wider band


def test_time_in_range_for_bounds() -> None:
    wide = time_in_range_for_bounds(1700, 1500, 1900, 0.0066, 7, seed=7)
    narrow = time_in_range_for_bounds(1700, 1680, 1720, 0.0066, 7, seed=7)
    assert 0.0 <= narrow < wide <= 1.0
    off = time_in_range_for_bounds(1700, 2000, 2200, 0.0066, 7, seed=7)  # excludes price
    assert off < 0.2
