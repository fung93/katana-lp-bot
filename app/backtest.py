"""Backtest harness (cross-cutting): replay a range strategy over REAL ETH price
history to sanity-check the /suggest time-in-range model against what actually
happened.

It's an in-sample reality check: it uses the same recent window the vol estimate
came from, so it answers "did this width actually hold the price in range
recently?" rather than being a true out-of-sample forecast. Honest, useful, and
catches when the random-walk model diverges from a trending/clustered market.
"""
from __future__ import annotations

import math


def backtest_width(closes: list[float], half_width: float,
                   horizon_hours: int) -> tuple[float, int]:
    """Average realized time-in-range for a centered +/- half_width (log) range,
    across every rolling horizon-length window of `closes`.

    For each window: open centered at that hour's price, then measure the fraction
    of the next `horizon_hours` the price stayed within the band. Returns
    (avg_time_in_range, n_windows).
    """
    n = len(closes)
    if n <= horizon_hours or half_width <= 0:
        return 0.0, 0
    tirs = []
    for start in range(n - horizon_hours):
        p0 = closes[start]
        lo, hi = p0 * math.exp(-half_width), p0 * math.exp(half_width)
        window = closes[start + 1: start + 1 + horizon_hours]
        in_range = sum(1 for p in window if lo <= p <= hi)
        tirs.append(in_range / len(window))
    return (sum(tirs) / len(tirs), len(tirs)) if tirs else (0.0, 0)


def historical_time_in_range(closes: list[float], lower: float, upper: float) -> float:
    """Fraction of the history the price sat within a fixed [lower, upper]."""
    if not closes:
        return 0.0
    return sum(1 for p in closes if lower <= p <= upper) / len(closes)
