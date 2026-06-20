"""Tiny forward-only SQL migration runner.

Applies ``migrations/*.sql`` in filename order, each recorded in a
``schema_migrations`` table. Idempotent: re-running applies only new files. No
ORM, no Alembic - plain SQL you can read and a thin runner you can audit.

    python -m app.migrate
"""
from __future__ import annotations

import pathlib
import sys

from .db import connect

MIGRATIONS_DIR = pathlib.Path(__file__).resolve().parent.parent / "migrations"


def _ensure_table(cur) -> None:
    cur.execute(
        """
        create table if not exists schema_migrations (
            version    text primary key,
            applied_at timestamptz not null default now()
        )
        """
    )


def _applied(cur) -> set[str]:
    cur.execute("select version from schema_migrations")
    return {row[0] for row in cur.fetchall()}


def run() -> None:
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        print("No migration files found in", MIGRATIONS_DIR)
        return

    conn = connect()
    try:
        with conn.cursor() as cur:
            _ensure_table(cur)
        conn.commit()

        with conn.cursor() as cur:
            done = _applied(cur)

        applied = 0
        for path in files:
            version = path.name
            if version in done:
                print(f"= skip    {version} (already applied)")
                continue
            sql = path.read_text(encoding="utf-8")
            with conn.cursor() as cur:
                cur.execute(sql)
                cur.execute(
                    "insert into schema_migrations (version) values (%s)", (version,)
                )
            conn.commit()
            applied += 1
            print(f"+ applied {version}")

        print(f"Done. {applied} new migration(s); {len(files)} total on disk.")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:
        print(f"Migration failed: {exc}", file=sys.stderr)
        sys.exit(1)
