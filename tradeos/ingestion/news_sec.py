"""SEC 8-K material-events news ingester (News Intelligence, Milestone 1).

8-K is the form public companies must file for material corporate events — earnings releases,
executive departures, acquisitions, new agreements, delisting notices, impairments. It is the
cleanest primary-source "breaking corporate news" feed there is, and it is free and keyless.

Trust discipline, same as the Schedule 13D/G pipeline (docs/threat-models/schedule13.md):
  - We read the machine-structured SGML header for the authoritative facts (registrant CIK/name,
    acceptance time), never guess from the free-form body.
  - The one thing we DO read from the body is the set of standardized Item codes ("Item 5.02"),
    which are a controlled vocabulary — so "what happened" is mapped from a fixed table, not
    interpreted. Interpretation is the AI plane's job (intelligence/analyst.py), held to its guards.

Scope: we only ingest 8-Ks whose registrant maps to a ticker we already track, so this feed is
"material events on names a user can actually act on". Broad market/macro news comes from the RSS
source. Point-in-time: knowable_time = ACCEPTANCE-DATETIME (US/Eastern).
"""
from __future__ import annotations

import logging
import re
from datetime import date
from zoneinfo import ZoneInfo

import psycopg
from psycopg.types.json import Json

from . import form4, sgml
from .common import reject, update_health
from .edgar_client import EdgarClient
from .runner import master_index_url

log = logging.getLogger("tradeos.ingest.news_sec")
SOURCE = "sec/8-k"
EASTERN = ZoneInfo("America/New_York")
FORM_TYPES = {"8-K", "8-K/A"}

# The standardized 8-K item taxonomy → a plain-language label. A controlled vocabulary, so the
# headline is a lookup, never a guess. (SEC General Instruction B / Form 8-K item list.)
ITEM_LABELS = {
    "1.01": "Entered a material agreement",
    "1.02": "Terminated a material agreement",
    "1.03": "Bankruptcy or receivership",
    "1.04": "Mine safety disclosure",
    "1.05": "Material cybersecurity incident",
    "2.01": "Completed an acquisition or disposition",
    "2.02": "Reported results of operations",           # quarterly/annual earnings
    "2.03": "Took on a financial obligation",
    "2.04": "Triggered an obligation acceleration",
    "2.05": "Costs from exit or disposal activities",
    "2.06": "Material asset impairment",
    "3.01": "Delisting or listing-rule notice",
    "3.02": "Unregistered sale of equity",
    "3.03": "Change to shareholder rights",
    "4.01": "Changed its accountants",
    "4.02": "Prior financial statements no longer reliable",
    "5.01": "Change in control of the company",
    "5.02": "Executive or board change",
    "5.03": "Charter or bylaw amendment",
    "5.07": "Shareholder vote results",
    "5.08": "Shareholder director nominations",
    "6.01": "ABS informational/computational material",
    "7.01": "Regulation FD disclosure",
    "8.01": "Other material event",
    "9.01": "Financial statements and exhibits",
}

# When several items are present, the headline leads with the most market-relevant one.
_ITEM_SALIENCE = [
    "1.03", "4.02", "5.01", "2.01", "2.06", "3.01", "2.02", "5.02", "1.05",
    "1.01", "2.03", "2.04", "3.02", "4.01", "5.03", "5.07", "7.01", "8.01",
]
CATEGORY_BY_ITEM = {
    "2.02": "earnings",
    "2.01": "ma", "5.01": "ma",
    "5.02": "officer_change",
    "1.03": "distress", "4.02": "distress", "3.01": "distress", "2.06": "distress",
    "2.04": "distress", "1.05": "distress",
    "1.01": "agreement", "1.02": "agreement",
    "2.03": "financing", "3.02": "financing",
    "5.07": "governance", "5.03": "governance", "5.08": "governance",
    "7.01": "disclosure", "8.01": "general", "9.01": "general",
}

_ITEM_RE = re.compile(r"Item[\s ]+(\d\.\d{2})", re.IGNORECASE)


# ------------------------------------------------------------------ pure: item extraction + headline

def extract_items(text: str) -> list[str]:
    """Distinct known 8-K item codes in the order they first appear. Pure + offline-testable."""
    seen: list[str] = []
    for m in _ITEM_RE.finditer(text):
        code = m.group(1)
        if code in ITEM_LABELS and code not in seen:
            seen.append(code)
    return seen


def _primary_item(items: list[str]) -> str:
    for code in _ITEM_SALIENCE:
        if code in items:
            return code
    return items[0]


def compose(company: str, items: list[str]) -> tuple[str, str, str]:
    """(headline, summary, category) from the registrant name and its item codes — a lookup, never
    an interpretation. Interpretation ('why it matters') is the guarded AI plane's job."""
    company = (company or "A company").strip().title() if (company or "").isupper() else (company or "A company").strip()
    if not items:
        return (f"{company} filed an 8-K (material event)",
                "Material 8-K filed; item detail not machine-readable in the header.", "general")
    primary = _primary_item(items)
    category = CATEGORY_BY_ITEM.get(primary, "general")
    lead = ITEM_LABELS[primary]
    extra = len(items) - 1
    headline = f"{company}: {lead.lower()}" + (f" (+{extra} more)" if extra > 0 else "")
    summary = "; ".join(ITEM_LABELS[i] for i in items) + "."
    return headline, summary, category


# ------------------------------------------------------------------ DB gather + ingest

def _ticker_universe(conn: psycopg.Connection) -> dict[str, tuple[int, str, str]]:
    """{normalized_cik: (entity_id, symbol, name)} for every tracked, tickered name — the pre-filter
    that keeps us from fetching thousands of 8-Ks from tiny filers with no ticker."""
    out: dict[str, tuple[int, str, str]] = {}
    with conn.cursor() as cur:
        cur.execute(
            """SELECT e.cik, e.id, e.name,
                      (SELECT symbol FROM security_map m WHERE m.entity_id=e.id
                         AND m.source='sec_company_tickers' ORDER BY confidence DESC LIMIT 1) sym
               FROM entities e WHERE e.cik IS NOT NULL""")
        for cik, eid, name, sym in cur.fetchall():
            if sym and cik:
                out[cik] = (eid, sym, name)
    return out


def ingest_day(conn: psycopg.Connection, client: EdgarClient, day: date, limit: int | None = None) -> dict:
    """One day of 8-K material events for tracked, tradeable names. Idempotent (external_id =
    accession_no). Returns counters."""
    counters = {"items": 0, "skipped": 0, "rejected": 0, "off_universe": 0}
    index = client.get(master_index_url(day))
    rows = form4.parse_master_index(index.content.decode("latin-1"), form_types=FORM_TYPES)
    universe = _ticker_universe(conn)
    kept = []
    for r in rows:
        ck = sgml.norm_cik(r.cik)
        if ck in universe:
            kept.append((r, ck))
        else:
            counters["off_universe"] += 1
    if limit:
        kept = kept[:limit]
    log.info("day %s: %d 8-K filings, %d on tracked names", day, len(rows), len(kept))

    for row, ck in kept:
        try:
            _ingest_filing(conn, client, row, universe[ck], counters)
            conn.commit()
        except Exception as exc:  # one bad filing must never kill the day
            conn.rollback()
            reject(conn, SOURCE, row.accession_no, f"{type(exc).__name__}: {exc}", counters)
            conn.commit()

    with conn.cursor() as cur:
        cur.execute("SELECT max(knowable_time) FROM news_items WHERE source=%s", (SOURCE,))
        freshest = cur.fetchone()[0]
    update_health(conn, SOURCE, counters["items"], counters["rejected"], freshest)
    conn.commit()
    return counters


def _ingest_filing(conn, client, row, mapped: tuple[int, str, str], counters: dict) -> None:
    entity_id, symbol, name = mapped
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM news_items WHERE source=%s AND external_id=%s", (SOURCE, row.accession_no))
        if cur.fetchone():
            counters["skipped"] += 1
            return

    fetched = client.get(row.url)
    text = fetched.content.decode("latin-1")
    header = sgml.parse_header(text)
    if header.submission_type not in FORM_TYPES:
        raise ValueError(f"unexpected submission type {header.submission_type!r}")

    knowable = header.acceptance.replace(tzinfo=EASTERN)
    company = (header.filers[0].name if header.filers else None) or name or row.company
    items = extract_items(text)
    headline, summary, category = compose(company, items)
    meta = {"items": items, "sha256": fetched.sha256, "form_type": header.submission_type,
            "period_of_report": header.period_of_report.isoformat() if header.period_of_report else None}

    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO news_items (source, external_id, url, headline, summary, category,
                                       published_at, knowable_time, meta)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (source, external_id) DO NOTHING RETURNING id""",
            (SOURCE, row.accession_no, row.url, headline, summary, category, knowable, knowable, Json(meta)))
        r = cur.fetchone()
        if r is None:  # lost a race; treat as skip
            counters["skipped"] += 1
            return
        news_id = r[0]
        cur.execute(
            """INSERT INTO news_item_entities (news_id, entity_id, symbol, relation)
               VALUES (%s,%s,%s,'primary') ON CONFLICT (news_id, symbol) DO NOTHING""",
            (news_id, entity_id, symbol))
    counters["items"] += 1
