"""Neon/Postgres access for the LP bot - psycopg v3 with cold-start retry.

Neon scales compute to zero when idle, so the first connection after a quiet
spell can fail or stall while the database wakes. ``connect()`` retries with
exponential backoff, turning a cold start into a short delay rather than an
error.

Carry-over note: this mirrors the perps bot's db.py pattern (pooled Neon
connection string + cold-start retry). If your perps bot's db.py differs in
shape, share it and I'll align this exactly.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Iterator

import psycopg

from .config import get_database_url

_RETRIES = 5
_BACKOFF_BASE = 0.5  # seconds: 0.5, 1.0, 2.0, 4.0 between attempts


def connect() -> psycopg.Connection:
    """Open a connection to Neon, retrying through a cold start."""
    last: Exception | None = None
    for attempt in range(_RETRIES):
        try:
            return psycopg.connect(get_database_url(), connect_timeout=10)
        except psycopg.OperationalError as exc:  # cold start / transient network
            last = exc
            if attempt == _RETRIES - 1:
                break
            time.sleep(_BACKOFF_BASE * (2 ** attempt))
    raise RuntimeError(
        f"Could not connect to Neon after {_RETRIES} attempts (cold start?)."
    ) from last


@contextmanager
def get_cursor(commit: bool = True) -> Iterator[psycopg.Cursor]:
    """Cursor context manager: commits on success, rolls back on error."""
    conn = connect()
    try:
        with conn.cursor() as cur:
            yield cur
        if commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def healthcheck() -> bool:
    """`SELECT 1` round-trip - confirms the database is reachable."""
    with get_cursor(commit=False) as cur:
        cur.execute("select 1")
        row = cur.fetchone()
        return bool(row and row[0] == 1)
