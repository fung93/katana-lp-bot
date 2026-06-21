"""Tests for the backtest harness (deterministic synthetic series)."""
from __future__ import annotations

import math
import random

from app.backtest import backtest_width, historical_time_in_range


def test_historical_time_in_range() -> None:
    closes = [100, 110, 120, 105, 95]
    assert historical_time_in_range(closes, 100, 115) == 3 / 5   # 100, 110, 105
    assert historical_time_in_range(closes, 0, 1000) == 1.0
    assert historical_time_in_range(closes, 200, 300) == 0.0


def test_flat_price_is_always_in_range() -> None:
    avg, n = backtest_width([100.0] * 100, 0.05, 24)
    assert n > 0
    assert avg == 1.0


def test_wider_band_has_more_time_in_range() -> None:
    rng = random.Random(0)
    closes = [100.0]
    for _ in range(500):
        closes.append(closes[-1] * math.exp(rng.gauss(0, 0.01)))
    narrow, _ = backtest_width(closes, 0.01, 24)
    wide, _ = backtest_width(closes, 0.10, 24)
    assert 0.0 <= narrow < wide <= 1.0


def test_too_short_history_returns_zero() -> None:
    assert backtest_width([100.0] * 10, 0.05, 24) == (0.0, 0)
