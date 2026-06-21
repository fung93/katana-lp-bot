"""Vol-based range suggester (Phase 4).

Given realized hourly volatility, find the symmetric (in log-price) range
half-width whose expected time-in-range hits a target, via a small zero-drift
Monte Carlo. Pure stdlib; deterministic with a fixed seed.

Zero drift is the neutral assumption for a range suggester. Symmetric-in-log maps
naturally onto a symmetric tick range (ticks are log-spaced). Time-in-range is the
expected fraction of hourly steps the price sits inside the range over the horizon.
"""
from __future__ import annotations

import bisect
import math
import random
from dataclasses import dataclass


def _sim_logprices(sigma_hourly: float, horizon_hours: int, n_paths: int,
                   seed: int) -> list[float]:
    """Sorted log-price offsets over all (path, step) pairs of a 0-drift walk."""
    rng = random.Random(seed)
    vals: list[float] = []
    for _ in range(n_paths):
        lp = 0.0
        for _ in range(horizon_hours):
            lp += rng.gauss(0.0, sigma_hourly)
            vals.append(lp)
    vals.sort()
    return vals


def _time_in_range(sorted_vals: list[float], half_width: float) -> float:
    lo = bisect.bisect_left(sorted_vals, -half_width)
    hi = bisect.bisect_right(sorted_vals, half_width)
    return (hi - lo) / len(sorted_vals)


@dataclass
class Suggestion:
    lower_price: float
    upper_price: float
    half_width_pct: float       # +/- % band around the current price (log)
    time_in_range: float        # estimated fraction in [0, 1]


def suggest_range(price: float, sigma_hourly: float, days: float, target_tir: float,
                  n_paths: int = 2000, seed: int = 42) -> Suggestion:
    """Symmetric range whose expected time-in-range ~= target_tir."""
    horizon = max(1, int(round(days * 24)))
    vals = _sim_logprices(sigma_hourly, horizon, n_paths, seed)
    lo, hi = 0.0, (vals[-1] if vals else 1.0)
    for _ in range(50):                       # bisect the half-width (TIR rises with width)
        mid = (lo + hi) / 2
        if _time_in_range(vals, mid) < target_tir:
            lo = mid
        else:
            hi = mid
    w = hi
    return Suggestion(
        lower_price=price * math.exp(-w),
        upper_price=price * math.exp(w),
        half_width_pct=(math.exp(w) - 1) * 100,
        time_in_range=_time_in_range(vals, w),
    )
