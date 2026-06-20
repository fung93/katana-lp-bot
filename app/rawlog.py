"""Append-only raw log of what the bot read (Phase 1).

No position data yet - just a timestamped record of each fetch, so the live
numbers behind future net-P&L work can be audited later. Writes JSON lines to a
gitignored data/ directory and never raises: a logging failure must not break a
command.
"""
from __future__ import annotations

import json
import pathlib
import time

LOG_PATH = pathlib.Path(__file__).resolve().parent.parent / "data" / "raw_log.jsonl"


def record(kind: str, **fields) -> None:
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        entry = {"ts": time.time(), "kind": kind, **fields}
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except Exception:
        pass
