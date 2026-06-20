"""Position logging against Neon (Phase 2).

Bounds are stored as INTEGER TICKS; the human only ever enters and reads USD
prices, which this module converts at the boundary via tickmath.

Because token0 is the stablecoin, a LOWER USD price maps to a HIGHER tick. To
keep the schema's tickLower < tickUpper invariant we store
    lower_bound = min(tick(priceA), tick(priceB))
    upper_bound = max(tick(priceA), tick(priceB))
so the caller never has to reason about the inversion. On the way out,
price_low/price_high convert back to USD for display.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .config import get_pool_address
from .db import get_cursor
from .liquidity import composition, liquidity_for_capital
from .tickmath import price_to_tick, tick_to_price

DEFAULT_FEE_TIER = 500  # Uniswap fee units: 500 = 0.05%

_COLUMNS = """
    id, status, pool_address, fee_tier, entry_price, lower_bound, upper_bound,
    capital_usd, amount_eth, amount_usdc, opened_at, closed_at, kat_at_open
"""


@dataclass
class Position:
    id: str
    status: str
    pool_address: str
    fee_tier: int
    entry_price: float | None
    lower_tick: int
    upper_tick: int
    capital_usd: float | None
    amount_eth: float | None
    amount_usdc: float | None
    opened_at: datetime
    closed_at: datetime | None
    kat_at_open: float | None = None

    @property
    def price_high(self) -> float:
        """Upper USD bound (the lower tick maps to the higher price)."""
        return tick_to_price(self.lower_tick)

    @property
    def price_low(self) -> float:
        """Lower USD bound (the upper tick maps to the lower price)."""
        return tick_to_price(self.upper_tick)

    def in_range(self, current_tick: int) -> bool:
        return self.lower_tick <= current_tick <= self.upper_tick


def bounds_to_ticks(price_a: float, price_b: float) -> tuple[int, int]:
    """Two USD price bounds -> (lower_tick, upper_tick) with lower_tick < upper_tick."""
    t1, t2 = price_to_tick(price_a), price_to_tick(price_b)
    return (min(t1, t2), max(t1, t2))


def _row_to_position(r) -> Position:
    def f(x):
        return float(x) if x is not None else None
    return Position(
        id=str(r[0]), status=r[1], pool_address=r[2], fee_tier=r[3],
        entry_price=f(r[4]), lower_tick=r[5], upper_tick=r[6],
        capital_usd=f(r[7]), amount_eth=f(r[8]), amount_usdc=f(r[9]),
        opened_at=r[10], closed_at=r[11], kat_at_open=f(r[12]),
    )


def open_position(*, entry_price: float, lower_price: float, upper_price: float,
                  capital_usd: float, amount_eth: float, amount_usdc: float,
                  fee_tier: int = DEFAULT_FEE_TIER, pool_address: str | None = None,
                  kat_at_open: float | None = None) -> Position:
    pool_address = pool_address or get_pool_address()
    lower_tick, upper_tick = bounds_to_ticks(lower_price, upper_price)
    with get_cursor() as cur:
        cur.execute(
            """
            insert into positions
              (status, pool_address, fee_tier, entry_price, lower_bound, upper_bound,
               capital_usd, amount_eth, amount_usdc, kat_at_open)
            values ('open', %s, %s, %s, %s, %s, %s, %s, %s, %s)
            returning """ + _COLUMNS,
            (pool_address, fee_tier, entry_price, lower_tick, upper_tick,
             capital_usd, amount_eth, amount_usdc, kat_at_open),
        )
        pos = _row_to_position(cur.fetchone())
        cur.execute(
            "insert into position_events (position_id, kind, price, note) "
            "values (%s, 'open', %s, 'opened')",
            (pos.id, entry_price),
        )
    return pos


def list_open() -> list[Position]:
    with get_cursor(commit=False) as cur:
        cur.execute(f"select {_COLUMNS} from positions where status='open' order by opened_at")
        return [_row_to_position(r) for r in cur.fetchall()]


def find_open_by_prefix(prefix: str) -> list[Position]:
    with get_cursor(commit=False) as cur:
        cur.execute(
            f"select {_COLUMNS} from positions "
            "where status='open' and id::text like %s order by opened_at",
            (prefix + "%",),
        )
        return [_row_to_position(r) for r in cur.fetchall()]


def get_position(pos_id: str) -> Position | None:
    with get_cursor(commit=False) as cur:
        cur.execute(f"select {_COLUMNS} from positions where id=%s", (pos_id,))
        r = cur.fetchone()
        return _row_to_position(r) if r else None


def close_position(pos_id: str, *, exit_price: float, fees_earned: float | None = None,
                   kat_earned: float | None = None, gas_paid: float | None = None) -> Position:
    with get_cursor() as cur:
        cur.execute(
            "update positions set status='closed', closed_at=now() "
            "where id=%s and status='open' returning id",
            (pos_id,),
        )
        if cur.fetchone() is None:
            raise ValueError("position not found or already closed")
        cur.execute(
            """
            insert into position_events
              (position_id, kind, price, fees_earned, kat_earned, gas_paid, note)
            values (%s, 'close', %s, %s, %s, %s, 'closed')
            """,
            (pos_id, exit_price, fees_earned, kat_earned, gas_paid),
        )
    closed = get_position(pos_id)
    assert closed is not None
    return closed


@dataclass
class ExitReport:
    """What the position holds at a given exit price, and its value change."""
    exit_price: float
    eth_exit: float
    usdc_exit: float
    entry_value: float
    exit_value: float
    delta: float


def exit_report(pos: Position, exit_price: float) -> ExitReport:
    """Model the position's composition + value at exit_price (V3 closed form)."""
    if pos.capital_usd is None or pos.entry_price is None:
        raise ValueError("position is missing capital or entry price")
    liq = liquidity_for_capital(
        pos.capital_usd, pos.entry_price, pos.lower_tick, pos.upper_tick
    )
    usdc_exit, eth_exit = composition(exit_price, pos.lower_tick, pos.upper_tick, liq)
    exit_value = usdc_exit + eth_exit * exit_price
    return ExitReport(
        exit_price=exit_price, eth_exit=eth_exit, usdc_exit=usdc_exit,
        entry_value=pos.capital_usd, exit_value=exit_value,
        delta=exit_value - pos.capital_usd,
    )
