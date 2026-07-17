"""Ingestion helpers shared across every feed: loud rejects and feed-health accounting.

A feed that degrades must degrade loudly (honesty rule 6). Rejects land in
`ingest_rejects` with a reason; `feed_health` carries per-source counts and the freshest
knowable record, which the product surfaces directly.
"""
from __future__ import annotations

import logging

import psycopg

log = logging.getLogger("tradeos.ingest")


def reject(conn: psycopg.Connection, source: str, accession: str | None, reason: str, counters: dict) -> None:
    counters["rejected"] += 1
    log.warning("REJECT [%s] %s: %s", source, accession, reason)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO ingest_rejects (source, accession_no, reason) VALUES (%s, %s, %s)",
            (source, accession, reason),
        )


def update_health(conn: psycopg.Connection, source: str, records: int, rejects: int, freshest_knowable) -> None:
    """Accumulate this run's counts into feed_health. `freshest_knowable` is the max
    knowable_time over the source's whole derived table, recomputed by the caller."""
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO feed_health (source, last_success_at, last_record_knowable, records_total, rejects_total)
               VALUES (%s, now(), %s, %s, %s)
               ON CONFLICT (source) DO UPDATE SET
                   last_success_at = now(),
                   last_record_knowable = EXCLUDED.last_record_knowable,
                   records_total = feed_health.records_total + EXCLUDED.records_total,
                   rejects_total = feed_health.rejects_total + EXCLUDED.rejects_total""",
            (source, freshest_knowable, records, rejects),
        )
