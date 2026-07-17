"""Canonical entities keyed on CIK, and the backfill that links Slice 1's insider rows.

Identity is the CIK; `kind` is a best-effort label set on first creation. One CIK maps to
exactly one entity even when it plays two roles (e.g. an asset manager that is itself a
listed issuer), because it is the same real-world party.
"""
from __future__ import annotations

import psycopg


def get_or_create_entity(cur: psycopg.Cursor, cik: str | None, name: str, kind: str) -> int:
    """Return the entity id for a CIK, creating it if unseen. CIK must already be
    normalized (leading zeros stripped) by the caller/sgml.norm_cik."""
    if cik:
        cur.execute(
            "INSERT INTO entities (kind, cik, name) VALUES (%s, %s, %s) ON CONFLICT (cik) DO NOTHING",
            (kind, cik, name),
        )
        cur.execute("SELECT id FROM entities WHERE cik = %s", (cik,))
        return cur.fetchone()[0]
    # no CIK: a bare entity (uncommon for our feeds, which always carry one)
    cur.execute("INSERT INTO entities (kind, name) VALUES (%s, %s) RETURNING id", (kind, name))
    return cur.fetchone()[0]


def backfill_insider_entities(conn: psycopg.Connection) -> int:
    """Link insider_transactions.issuer_entity by CIK, creating issuer entities for any
    issuer_cik not already present. Idempotent: only touches rows still unresolved."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT issuer_cik, issuer_name FROM insider_transactions WHERE issuer_entity IS NULL"
        )
        for cik, name in cur.fetchall():
            get_or_create_entity(cur, cik, name, "issuer")
        cur.execute(
            """UPDATE insider_transactions t SET issuer_entity = e.id
               FROM entities e WHERE e.cik = t.issuer_cik AND t.issuer_entity IS NULL"""
        )
        updated = cur.rowcount
    conn.commit()
    return updated
