"""Direct JSON-RPC reads from the Katana pool. Read-only: this bot never signs.

We deliberately avoid web3.py for now - a ``slot0()`` read is a single
``eth_call`` we can encode and decode by hand, so heavy ABI tooling isn't
justified yet. (If later phases need many contract calls, revisit.)
"""
from __future__ import annotations

from dataclasses import dataclass

import httpx

# keccak256("slot0()")[:4]
_SLOT0_SELECTOR = "0x3850c7bd"
_WORD = 32  # bytes per ABI-encoded word


@dataclass(frozen=True)
class Slot0:
    sqrt_price_x96: int
    tick: int


def _eth_call(rpc_url: str, to: str, data: str) -> bytes:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_call",
        "params": [{"to": to, "data": data}, "latest"],
    }
    resp = httpx.post(rpc_url, json=payload, timeout=15.0)
    resp.raise_for_status()
    body = resp.json()
    if body.get("error"):
        raise RuntimeError(f"RPC error: {body['error']}")
    result = body.get("result")
    if not result or result == "0x":
        raise RuntimeError("Empty eth_call result (wrong pool address or chain?)")
    return bytes.fromhex(result[2:])


def get_slot0(rpc_url: str, pool_address: str) -> Slot0:
    """Read Uniswap V3 ``slot0()``; decode sqrtPriceX96 (uint160) and tick (int24).

    The return ABI is seven 32-byte words; we only need the first two:
        word 0 = sqrtPriceX96 (uint160, unsigned)
        word 1 = tick         (int24, sign-extended to 32 bytes)
    """
    raw = _eth_call(rpc_url, pool_address, _SLOT0_SELECTOR)
    if len(raw) < 2 * _WORD:
        raise RuntimeError(f"Unexpected slot0 return length: {len(raw)} bytes")
    sqrt_price_x96 = int.from_bytes(raw[0:_WORD], "big")
    tick = int.from_bytes(raw[_WORD:2 * _WORD], "big", signed=True)
    return Slot0(sqrt_price_x96=sqrt_price_x96, tick=tick)


# keccak256("liquidity()")[:4]
_LIQUIDITY_SELECTOR = "0x1a686502"


def get_liquidity(rpc_url: str, pool_address: str) -> int:
    """Pool's current in-range liquidity (uint128) via liquidity()."""
    raw = _eth_call(rpc_url, pool_address, _LIQUIDITY_SELECTOR)
    return int.from_bytes(raw[0:_WORD], "big")
