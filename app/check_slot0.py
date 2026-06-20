"""One-shot proof-of-pipeline: read live slot0, print the ETH price via tickmath.

    python -m app.check_slot0

Needs RPC_URL (and optionally POOL_ADDRESS) in .env. Reads only - no keys, no
writes, no trades. Prints the raw tick and sqrtPriceX96 alongside the price so
any orientation/scale problem is obvious at a glance.
"""
from __future__ import annotations

import sys

from .chain import get_slot0
from .config import get_pool_address, get_rpc_url
from .tickmath import tick_to_price


def main() -> int:
    rpc_url = get_rpc_url()
    pool = get_pool_address()
    slot0 = get_slot0(rpc_url, pool)
    price = tick_to_price(slot0.tick)
    print(f"pool          {pool}")
    print(f"tick          {slot0.tick}")
    print(f"sqrtPriceX96  {slot0.sqrt_price_x96}")
    print(f"ETH price     ${price:,.2f}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # surface a clean message, not a traceback dump
        print(f"slot0 read failed: {exc}", file=sys.stderr)
        sys.exit(1)
