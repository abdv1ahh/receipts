"""Orchestrates one day of Form 4 ingestion. Idempotent by construction:
raw storage keys on accession number, derived rows key on (accession, seq, owner),
so re-running a day is a no-op, and derived tables can always be rebuilt from raw.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

import psycopg

from . import form4
from .edgar_client import EdgarClient

log = logging.getLogger("tradeos.ingest.form4")
SOURCE = "edgar/form4"
EASTERN = ZoneInfo("America/New_York")  # EDGAR acceptance timestamps are US Eastern


def master_index_url(day: date) -> str:
    quarter = (day.month - 1) // 3 + 1
    return f"https://www.sec.gov/Archives/edgar/daily-index/{day.year}/QTR{quarter}/master.{day:%Y%m%d}.idx"


def ingest_day(conn: psycopg.Connection, client: EdgarClient, day: date, limit: int | None = None) -> dict:
    """Returns counters: {'filings': n, 'transactions': n, 'skipped': n, 'rejected': n}."""
    counters = {"filings": 0, "transactions": 0, "skipped": 0, "rejected": 0}
    index = client.get(master_index_url(day))
    rows = form4.parse_master_index(index.content.decode("latin-1"))
    if limit:
        rows = rows[:limit]
    log.info("day %s: %d Form 4 filings in index", day, len(rows))

    for row in rows:
        try:
            _ingest_filing(conn, client, row, counters)
            conn.commit()
        except Exception as exc:  # one bad filing must never kill the day
            conn.rollback()
            _reject(conn, row.accession_no, f"{type(exc).__name__}: {exc}", counters)
            conn.commit()

    _update_health(conn, counters)
    conn.commit()
    return counters


def _ingest_filing(conn: psycopg.Connection, client: EdgarClient, row: form4.IndexRow, counters: dict) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM raw_filings WHERE accession_no = %s", (row.accession_no,))
        if cur.fetchone():
            counters["skipped"] += 1
            return

    fetched = client.get(row.url)
    text = fetched.content.decode("latin-1")
    accepted_naive, xml = form4.split_submission(text)
    accepted = accepted_naive.replace(tzinfo=EASTERN)
    filing = form4.parse_form4_xml(xml)

    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO raw_filings (source, accession_no, source_url, sha256, accepted_at, payload)
               VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (accession_no) DO NOTHING""",
            (SOURCE, row.accession_no, row.url, fetched.sha256, accepted, fetched.content),
        )
        today = datetime.now(tz=EASTERN).date()
        for txn in filing.transactions:
            problems = form4.validate_transaction(txn, today)
            if problems:
                _reject(conn, row.accession_no, "; ".join(problems), counters)
                continue
            for owner in filing.owners:
                cur.execute(
                    """INSERT INTO insider_transactions
                       (accession_no, seq, form_type, issuer_cik, issuer_name, symbol,
                        owner_cik, owner_name, is_director, is_officer, officer_title,
                        security_title, transaction_code, event_time, knowable_time,
                        shares, price_per_share, acquired_disposed, shares_after, direct_indirect)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (accession_no, seq, owner_cik) DO NOTHING""",
                    (row.accession_no, txn.seq, row.form_type, filing.issuer_cik, filing.issuer_name,
                     filing.symbol, owner.cik, owner.name, owner.is_director, owner.is_officer,
                     owner.officer_title, txn.security_title, txn.transaction_code, txn.event_time,
                     accepted, txn.shares, txn.price_per_share, txn.acquired_disposed,
                     txn.shares_after, txn.direct_indirect),
                )
                counters["transactions"] += 1
    counters["filings"] += 1


def _reject(conn: psycopg.Connection, accession: str | None, reason: str, counters: dict) -> None:
    counters["rejected"] += 1
    log.warning("REJECT %s: %s", accession, reason)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO ingest_rejects (source, accession_no, reason) VALUES (%s, %s, %s)",
            (SOURCE, accession, reason),
        )


def _update_health(conn: psycopg.Connection, counters: dict) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO feed_health (source, last_success_at, last_record_knowable, records_total, rejects_total)
               VALUES (%s, now(),
                       (SELECT max(knowable_time) FROM insider_transactions),
                       %s, %s)
               ON CONFLICT (source) DO UPDATE SET
                   last_success_at = now(),
                   last_record_knowable = EXCLUDED.last_record_knowable,
                   records_total = feed_health.records_total + EXCLUDED.records_total,
                   rejects_total = feed_health.rejects_total + EXCLUDED.rejects_total""",
            (SOURCE, counters["transactions"], counters["rejected"]),
        )
