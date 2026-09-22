"""Postgres connection and dead-simple ordered migration runner.

TWO DIRECTORIES, AND THE CHOICE BETWEEN THEM IS THE ONLY CLEVERNESS HERE.

`migrations/` holds 37 ordered files: the whole history of the research platform Receipts was
extracted from. Every one of them is still correct and an existing database has applied them all.
Replaying them on a NEW install would create 64 tables so that 19 could be used, most of them for
subsystems whose code is gone.

`migrations/baseline/` holds one file: the schema those 19 tables actually need, plus the three
trigger functions, plus a `schema_migrations` row for each of the 37 it stands in for.

The rule is `schema_migrations`: empty means a fresh database, which gets the baseline; anything
else means a database with history, which gets the ordered files exactly as before. There is no
flag, no environment variable and no way for an operator to pick wrong, because the wrong choice
on an existing database is the one that would hurt — the baseline's CREATE TABLEs would fail
against tables that already exist, and a half-applied baseline is a schema nobody planned.
"""
from __future__ import annotations

import re
from pathlib import Path

import psycopg

from .config import database_url

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
BASELINE_DIR = MIGRATIONS_DIR / "baseline"


def connect() -> psycopg.Connection:
    return psycopg.connect(database_url())


def applied_versions(conn: psycopg.Connection) -> set[int]:
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('schema_migrations')")
        if cur.fetchone()[0] is None:
            return set()
        cur.execute("SELECT version FROM schema_migrations")
        return {row[0] for row in cur.fetchall()}


def _ordered(directory: Path) -> list[tuple[int, Path]]:
    out = []
    for path in sorted(directory.glob("*.sql")):
        m = re.match(r"(\d+)_", path.name)
        if m:
            out.append((int(m.group(1)), path))
    return out


def run_migrations(conn: psycopg.Connection) -> list[int]:
    """Bring the database up to date. Returns the versions applied, in order.

    A FRESH DATABASE TAKES THE BASELINE AND REPORTS THE 37 IT COVERS, not the baseline's own `1`.
    The version numbers in `schema_migrations` are what every later migration and `cli preflight`
    compare against, so a fresh install has to end up indistinguishable from a migrated one. The
    baseline's filename number is an ordering device inside its own directory and never a version.
    """
    done = applied_versions(conn)
    if not done and BASELINE_DIR.is_dir() and _ordered(BASELINE_DIR):
        for _, path in _ordered(BASELINE_DIR):
            with conn.cursor() as cur:
                cur.execute(path.read_text())
            conn.commit()
        return sorted(applied_versions(conn))

    ran: list[int] = []
    for version, path in _ordered(MIGRATIONS_DIR):
        if version in done:
            continue
        with conn.cursor() as cur:
            cur.execute(path.read_text())
        conn.commit()
        ran.append(version)
    return ran
