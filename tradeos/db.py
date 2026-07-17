"""Postgres connection and dead-simple ordered migration runner."""
from __future__ import annotations

import re
from pathlib import Path

import psycopg

from .config import database_url

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def connect() -> psycopg.Connection:
    return psycopg.connect(database_url())


def applied_versions(conn: psycopg.Connection) -> set[int]:
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('schema_migrations')")
        if cur.fetchone()[0] is None:
            return set()
        cur.execute("SELECT version FROM schema_migrations")
        return {row[0] for row in cur.fetchall()}


def run_migrations(conn: psycopg.Connection) -> list[int]:
    done = applied_versions(conn)
    ran: list[int] = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        m = re.match(r"(\d+)_", path.name)
        if not m:
            continue
        version = int(m.group(1))
        if version in done:
            continue
        with conn.cursor() as cur:
            cur.execute(path.read_text())
        conn.commit()
        ran.append(version)
    return ran
