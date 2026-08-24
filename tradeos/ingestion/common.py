"""Ingestion helpers shared across every feed: loud rejects and feed-health accounting.

A feed that degrades must degrade loudly (honesty rule 6). Rejects land in
`ingest_rejects` with a reason; `feed_health` carries per-source counts and the freshest
knowable record, which the product surfaces directly.

Degrading loudly must not mean degrading *indiscreetly*: five adapters hand raw exception text to
`reject`, and httpx puts the full request URL — query string included — in that text. Tiingo
authenticates with `?token=`, so 1,172 reject rows had the live API key stored in plain text going
back to 2026-07-16. Redaction therefore happens INSIDE `reject`, not at the five call sites, so a
sixth adapter cannot reintroduce it by forgetting.
"""
from __future__ import annotations

import logging
import re

import psycopg

log = logging.getLogger("tradeos.ingest")

# Everything from the first `?` or `&` to the next whitespace or quote. Deliberately blunt: losing
# a harmless query parameter from an error message costs nothing, and keeping a credential costs
# the key. This is the same rule as `scheduler.redact`, which now delegates here rather than
# keeping a second copy — a formatter duplicated across files drifts, and this one must not.
_QUERY = re.compile(r"(\?|&)[^\s'\"]+")


def redact(text: str) -> str:
    """An error message with query strings removed, so a credential passed as a URL parameter never
    reaches the database or the logs. Pure and offline-testable."""
    return _QUERY.sub(r"\1<redacted>", text or "")


def reject(conn: psycopg.Connection, source: str, accession: str | None, reason: str, counters: dict) -> None:
    reason = redact(reason)
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
