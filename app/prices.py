"""ETH/USD price history + realized volatility for the range suggester (Phase 4).

Used only by the interactive /suggest command, never the monitor loop. Binance is
geo-blocked from here, so we use Kraken (primary) with a Coingecko fallback - both
free, no key, no KYC. The pool tracks ETH/USD, so global ETH vol is a fair proxy
for the pool's price volatility.
"""
from __future__ import annotations

import math
import statistics

import httpx


def _kraken_hourly() -> list[float]:
    r = httpx.get("https://api.kraken.com/0/public/OHLC",
                  params={"pair": "ETHUSD", "interval": 60}, timeout=15)
    r.raise_for_status()
    res = r.json().get("result", {})
    keys = [k for k in res if k != "last"]
    if not keys:
        raise RuntimeError("kraken: no OHLC data")
    return [float(row[4]) for row in res[keys[0]]]  # close column


def _coingecko_hourly() -> list[float]:
    r = httpx.get("https://api.coingecko.com/api/v3/coins/ethereum/market_chart",
                  params={"vs_currency": "usd", "days": "30"}, timeout=15)
    r.raise_for_status()
    return [p[1] for p in r.json().get("prices", [])]


def fetch_eth_closes() -> list[float]:
    """Recent hourly ETH/USD closes. Kraken primary, Coingecko fallback."""
    errors = []
    for src in (_kraken_hourly, _coingecko_hourly):
        try:
            closes = src()
            if len(closes) > 24:
                return closes
        except Exception as exc:
            errors.append(f"{src.__name__}: {exc}")
    raise RuntimeError("no ETH price source reachable (" + "; ".join(errors) + ")")


def hourly_vol(closes: list[float]) -> float:
    """Std-dev of hourly log returns (realized volatility, per hour)."""
    rets = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
    return statistics.pstdev(rets) if len(rets) > 1 else 0.0


def eth_hourly_vol() -> tuple[float, float]:
    """(hourly_vol, latest_history_price) from live data."""
    closes = fetch_eth_closes()
    return hourly_vol(closes), closes[-1]
