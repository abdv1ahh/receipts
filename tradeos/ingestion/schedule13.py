"""Schedule 13D / 13G pipeline: large-stake and activist filings.

Parse strategy is header-only by design (docs/threat-models/schedule13.md, decision #19):
the SGML header gives filer + subject-company CIK/name, form type, acceptance, SEC file
number, and period-of-report when present. We never scrape the free-form HTML cover page,
so percent_owned is stored NULL rather than guessed, and event_time falls back to the
filing date (flagged in parse_confidence) when the header carries no period.

Point-in-time discipline:
  event_time    = CONFORMED PERIOD OF REPORT (date of event) when present, else filing date
  knowable_time = ACCEPTANCE-DATETIME (US/Eastern)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

import psycopg

from . import form4, sgml
from .common import reject, update_health
from .edgar_client import EdgarClient
from ..resolution.entities import get_or_create_entity

log = logging.getLogger("tradeos.ingest.schedule13")
SOURCE = "edgar/13dg"
EASTERN = ZoneInfo("America/New_York")

# The daily master index labels these SCHEDULE 13x (not the "SC 13D" shorthand).
FORM_TYPES = {"SCHEDULE 13D", "SCHEDULE 13G", "SCHEDULE 13D/A", "SCHEDULE 13G/A"}
ACTIVIST = {"SCHEDULE 13D", "SCHEDULE 13D/A"}
AMENDMENTS = {"SCHEDULE 13D/A", "SCHEDULE 13G/A"}


class StakeParseError(ValueError):
    pass


@dataclass
class StakeRecord:
    accession_no: str
    form_type: str
    file_number: str | None
    filer_cik: str
    filer_name: str
    issuer_cik: str
    issuer_name: str
    event_time: date
    knowable_time: datetime          # US/Eastern, tz-aware
    parse_confidence: str            # 'header_period' | 'filing_date_fallback'
    activist: bool
    is_amendment: bool


def parse_stake(text: str) -> StakeRecord:
    h = sgml.parse_header(text)
    if h.submission_type not in FORM_TYPES:
        raise StakeParseError(f"unexpected submission type {h.submission_type!r}")
    if not h.filers or not h.filers[0].cik:
        raise StakeParseError("no filer CIK in header")
    if not h.subject_companies or not h.subject_companies[0].cik:
        raise StakeParseError("no subject-company CIK in header")

    filer, subject = h.filers[0], h.subject_companies[0]
    if h.period_of_report is not None:
        event_time, confidence = h.period_of_report, "header_period"
    elif h.filed_as_of_date is not None:
        event_time, confidence = h.filed_as_of_date, "filing_date_fallback"
    else:
        raise StakeParseError("no period-of-report or filing date in header")

    return StakeRecord(
        accession_no=h.accession_no,
        form_type=h.submission_type,
        file_number=h.file_number,
        filer_cik=filer.cik,
        filer_name=filer.name or "",
        issuer_cik=subject.cik,
        issuer_name=subject.name or "",
        event_time=event_time,
        knowable_time=h.acceptance.replace(tzinfo=EASTERN),
        parse_confidence=confidence,
        activist=h.submission_type in ACTIVIST,
        is_amendment=h.submission_type in AMENDMENTS,
    )


def validate_stake(rec: StakeRecord, today: date) -> list[str]:
    reasons: list[str] = []
    if rec.event_time > today:
        reasons.append(f"event_time {rec.event_time} is in the future")
    if rec.event_time.year < 1994:
        reasons.append(f"event_time {rec.event_time} predates EDGAR")
    if not rec.filer_cik:
        reasons.append("missing filer CIK")
    if not rec.issuer_cik:
        reasons.append("missing issuer CIK")
    if not rec.issuer_name:
        reasons.append("missing issuer name")
    return reasons


def ingest_day(conn: psycopg.Connection, client: EdgarClient, day: date, limit: int | None = None) -> dict:
    counters = {"filings": 0, "skipped": 0, "rejected": 0}
    from .runner import master_index_url  # same daily master.idx as Form 4
    index = client.get(master_index_url(day))
    rows = form4.parse_master_index(index.content.decode("latin-1"), form_types=FORM_TYPES)
    if limit:
        rows = rows[:limit]
    log.info("day %s: %d Schedule 13D/G filings in index", day, len(rows))

    for row in rows:
        try:
            _ingest_filing(conn, client, row, counters)
            conn.commit()
        except Exception as exc:  # one bad filing must never kill the day
            conn.rollback()
            reject(conn, SOURCE, row.accession_no, f"{type(exc).__name__}: {exc}", counters)
            conn.commit()

    with conn.cursor() as cur:
        cur.execute("SELECT max(knowable_time) FROM stake_events")
        freshest = cur.fetchone()[0]
    update_health(conn, SOURCE, counters["filings"], counters["rejected"], freshest)
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
    rec = parse_stake(text)

    today = datetime.now(tz=EASTERN).date()
    problems = validate_stake(rec, today)
    if problems:
        reject(conn, SOURCE, rec.accession_no, "; ".join(problems), counters)
        return

    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO raw_filings (source, accession_no, source_url, sha256, accepted_at, payload)
               VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (accession_no) DO NOTHING""",
            (SOURCE, row.accession_no, row.url, fetched.sha256, rec.knowable_time, fetched.content),
        )
        filer_entity = get_or_create_entity(cur, rec.filer_cik, rec.filer_name, "institution")
        issuer_entity = get_or_create_entity(cur, rec.issuer_cik, rec.issuer_name, "issuer")
        cur.execute(
            """INSERT INTO stake_events
               (accession_no, form_type, file_number, filer_entity, issuer_entity, issuer_name_raw,
                percent_owned, event_time, knowable_time, parse_confidence, activist)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (accession_no, filer_entity, issuer_name_raw) DO NOTHING""",
            (rec.accession_no, rec.form_type, rec.file_number, filer_entity, issuer_entity,
             rec.issuer_name, None, rec.event_time, rec.knowable_time, rec.parse_confidence, rec.activist),
        )
    counters["filings"] += 1
