"""Tick <-> human-price conversion for the vbUSDC/vbETH 0.05% pool on Katana.

This module is the single boundary where ticks (an internal storage detail) meet
USD prices (everything the human sees and types). Nothing outside this module
should do tick math.

==============================================================================
DERIVATION
==============================================================================
Uniswap V3 defines the price at tick ``i`` as the ratio of *raw* token amounts::

    P_raw(i) = 1.0001 ** i = token1_raw / token0_raw

For this pool::

    token0 = USDC, 6 decimals    (raw unit = 1e-6 USDC, "micro-USDC")
    token1 = WETH, 18 decimals   (raw unit = 1e-18 WETH, "wei")

so ``P_raw`` is (WETH wei) / (USDC micro): how many wei equal one micro-USDC at
the margin.

We want the HUMAN price the way you think about ETH: USDC per 1 ETH (~ USD/ETH).

Step 1 - strip decimals to get a human ratio::

    WETH_human = WETH_raw / 1e18
    USDC_human = USDC_raw / 1e6

    (WETH per USDC, human) = WETH_human / USDC_human
                           = (WETH_raw / 1e18) / (USDC_raw / 1e6)
                           = (WETH_raw / USDC_raw) * 1e(6 - 18)
                           = P_raw * 1e-12

Step 2 - invert, because you think in USDC/ETH, not ETH/USDC::

    ETH_USD = USDC per 1 ETH = 1 / (WETH per USDC, human)
            = 1 / (P_raw * 1e-12)
            = 1e12 / P_raw
            = 1e12 / 1.0001 ** tick

Both required corrections are visible in that one line:

  * the ``1e12`` factor  -> the 18-vs-6 decimal gap, i.e. 1e(18 - 6)
  * the reciprocal       -> the WETH/USDC (pool) vs USDC/ETH (human) inversion

==============================================================================
FORWARD / INVERSE
==============================================================================
::

    tick  -> price:  ETH_USD = 1e12 * 1.0001 ** (-tick)
    price -> tick:   tick    = ln(1e12 / ETH_USD) / ln(1.0001)
                             = (ln(1e12) - ln(ETH_USD)) / ln(1.0001)

Then snap to a valid initializable tick: the nearest multiple of tickSpacing
(10 for a 0.05% pool). One tick = a factor of 1.0001 = +0.01%; ten ticks =
~0.10%, so snapping moves the implied price by at most ~0.05%.

Sanity check: ETH_USD = $1708 -> tick ~= 201890 (snapped) -> $1708.0 back.

IMPORTANT ORIENTATION NOTE: because token0 is the stablecoin, ETH_USD is a
*decreasing* function of tick. A higher tick means a cheaper ETH. So do not be
surprised that the live tick for a ~$1700 ETH is a large *positive* number near
200,000 - that is correct, not a sign error.
"""
from __future__ import annotations

import math

# --- Pool constants: vbUSDC/vbETH 0.05% on Katana (chain 747474) ---
USDC_DECIMALS = 6     # token0
WETH_DECIMALS = 18    # token1
TICK_SPACING = 10     # 0.05% fee tier
TICK_BASE = 1.0001

# token1 - token0 decimal gap => 1e12 for this pool.
_DECIMAL_SHIFT = 10 ** (WETH_DECIMALS - USDC_DECIMALS)
_LN_BASE = math.log(TICK_BASE)
_LN_SHIFT = math.log(_DECIMAL_SHIFT)

# Uniswap V3 hard tick bounds.
MIN_TICK = -887272
MAX_TICK = 887272


def tick_to_price(tick: int) -> float:
    """Human ETH price in USD (USDC per 1 ETH) implied by a tick."""
    return _DECIMAL_SHIFT * (TICK_BASE ** (-tick))


def price_to_raw_tick(price_usd: float) -> float:
    """Unrounded (fractional) tick for a USD price. Mostly for tests/diagnostics."""
    if price_usd <= 0:
        raise ValueError("price_usd must be positive")
    return (_LN_SHIFT - math.log(price_usd)) / _LN_BASE


def align_to_spacing(tick: float, spacing: int = TICK_SPACING) -> int:
    """Snap a (possibly fractional) tick to the nearest valid multiple of spacing."""
    snapped = int(round(tick / spacing)) * spacing
    return max(MIN_TICK, min(MAX_TICK, snapped))


def price_to_tick(price_usd: float, spacing: int = TICK_SPACING) -> int:
    """USD price -> nearest VALID tick (a multiple of ``spacing``)."""
    return align_to_spacing(price_to_raw_tick(price_usd), spacing)
