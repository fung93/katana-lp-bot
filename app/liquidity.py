"""Uniswap/Sushi V3 liquidity-composition math for the vbUSDC/vbETH pool.

Given a logged position (capital, range, entry price) and a current/exit price,
compute how much USDC and ETH the position holds, via the standard V3 closed
form. Used to show exit composition and the entry->exit value change.

All prices are human USD/ETH; ticks are the stored integer bounds.
token0 = USDC (6 dp), token1 = WETH (18 dp). The raw sqrt price relates to the
human price by  sqrtP_raw = 10^((dec1-dec0)/2) / sqrt(price) = 1e6 / sqrt(price),
consistent with tickmath (ETH_USD = 1e12 / 1.0001^tick).

We anchor liquidity on the declared capital so entry value == capital exactly,
which sidesteps any small inconsistency in the manually entered token split.
"""
from __future__ import annotations

import math

from .tickmath import TICK_BASE, USDC_DECIMALS, WETH_DECIMALS

_SQRT_DEC = 10 ** ((WETH_DECIMALS - USDC_DECIMALS) / 2)  # 1e6
_USDC_UNIT = 10 ** USDC_DECIMALS
_WETH_UNIT = 10 ** WETH_DECIMALS


def _sqrt_raw_from_price(price_usd: float) -> float:
    return _SQRT_DEC / math.sqrt(price_usd)


def _sqrt_raw_from_tick(tick: int) -> float:
    return TICK_BASE ** (tick / 2)


def _amounts_per_liquidity(price_usd: float, lower_tick: int,
                           upper_tick: int) -> tuple[float, float]:
    """Raw token0(USDC) and token1(WETH) held per unit of liquidity at a price.

    Clamped at the range edges: below the range -> all WETH, above -> all USDC.
    """
    sa = _sqrt_raw_from_tick(lower_tick)   # smaller sqrt price (tickLower)
    sb = _sqrt_raw_from_tick(upper_tick)   # larger sqrt price (tickUpper)
    sp = min(max(_sqrt_raw_from_price(price_usd), sa), sb)
    amount0 = (sb - sp) / (sp * sb)        # USDC raw per unit L
    amount1 = (sp - sa)                    # WETH raw per unit L
    return amount0, amount1


def composition(price_usd: float, lower_tick: int, upper_tick: int,
                liquidity: float) -> tuple[float, float]:
    """(USDC, ETH) human amounts a position of given liquidity holds at price."""
    a0, a1 = _amounts_per_liquidity(price_usd, lower_tick, upper_tick)
    return liquidity * a0 / _USDC_UNIT, liquidity * a1 / _WETH_UNIT


def liquidity_for_capital(capital_usd: float, entry_price: float,
                          lower_tick: int, upper_tick: int) -> float:
    """Liquidity L such that the position is worth capital_usd at entry_price."""
    a0, a1 = _amounts_per_liquidity(entry_price, lower_tick, upper_tick)
    value_per_l = a0 / _USDC_UNIT + (a1 / _WETH_UNIT) * entry_price
    if value_per_l <= 0:
        raise ValueError("degenerate range or price")
    return capital_usd / value_per_l
