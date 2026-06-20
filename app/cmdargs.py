"""Tiny parsers for Telegram command input.

Kept free of telegram/db imports so it can be unit-tested in isolation. Accepts
human conveniences in numbers: a leading `$` and thousands `,` are stripped.
"""
from __future__ import annotations

_SKIP = {"skip", "-", "none", ""}


def to_amount(raw: str) -> float:
    """Parse a single numeric reply, tolerating `$` and `,`. Raises on garbage."""
    cleaned = raw.replace(",", "").replace("$", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        raise ValueError(f"not a number: '{raw}'")


def amount_or_skip(raw: str) -> float | None:
    """Like to_amount, but 'skip'/'-'/'none'/'' map to None (for optional fields)."""
    if raw.strip().lower() in _SKIP:
        return None
    return to_amount(raw)


def parse_kwargs(args: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for a in args:
        if "=" not in a:
            raise ValueError(f"expected key=value, got '{a}'")
        key, val = a.split("=", 1)
        key = key.strip().lower()
        if not key:
            raise ValueError(f"empty key in '{a}'")
        out[key] = val.strip()
    return out


def req_amount(kw: dict[str, str], key: str) -> float:
    if key not in kw:
        raise ValueError(f"missing {key}=")
    try:
        return to_amount(kw[key])
    except ValueError:
        raise ValueError(f"{key} must be a number, got '{kw[key]}'")


def opt_amount(kw: dict[str, str], key: str) -> float | None:
    return req_amount(kw, key) if key in kw else None
