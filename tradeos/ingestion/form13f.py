"""Form 13F-HR pipeline: quarterly institutional holdings.

Point-in-time discipline is load-bearing here (docs/threat-models/form13f.md):
  event_time    = CONFORMED PERIOD OF REPORT (quarter end)
  knowable_time = ACCEPTANCE-DATETIME (US/Eastern) — up to 45 days later; the gap IS the story

Two reality-driven rules baked in:
  - value normalized to whole USD (decision #17): thousands before the SEC's 2023-01-03
    amendment, whole dollars after; keyed on filing date.
  - holdings aggregated per (cusip, share_type) within a filing (decision #18): real info
    tables list one security many times (different managers/discretion); summing yields the
    filer's true total position and keeps the idempotency key intact.

XML is parsed with defusedxml; namespaced elements are matched with the {*} wildcard.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

import psycopg
from defusedxml import ElementTree as SafeET

from ..resolution.entities import get_or_create_entity
from . import form4, sgml
from .common import reject, update_health
from .edgar_client import EdgarClient

log = logging.getLogger("tradeos.ingest.form13f")
SOURCE = "edgar/13f"
EASTERN = ZoneInfo("America/New_York")

FORM_TYPES = {"13F-HR", "13F-HR/A"}
WHOLE_DOLLAR_FROM = date(2023, 1, 3)  # SEC amendment: value reported in whole USD on/after this


class Form13FParseError(ValueError):
    pass


@dataclass
class Holding:
    cusip: str
    issuer_name: str
    value_raw: Decimal          # as reported (thousands pre-2023, whole USD after)
    shares: Decimal | None
    share_type: str             # 'SH' or 'PRN'


@dataclass
class Filing13F:
    filer_cik: str
    filer_name: str
    period_end: date
    knowable_time: datetime
    holdings: list[Holding] = field(default_factory=list)


def normalize_value_usd(value_raw: Decimal, filed_on: date) -> Decimal:
    """Normalize the 13F value field to whole USD."""
    return value_raw if filed_on >= WHOLE_DOLLAR_FROM else value_raw * 1000


def _find_information_table(text: str) -> str | None:
    for block in re.findall(r"<XML>(.*?)</XML>", text, re.DOTALL):
        if "informationTable" in block:
            return block.strip()
    m = re.search(r"(<[^>]*informationTable\b.*?</[^>]*informationTable>)", text, re.DOTALL)
    return m.group(1).strip() if m else None


def _dec(el, tag: str) -> Decimal | None:
    found = el.find(f"{{*}}{tag}")
    if found is None or found.text is None or not found.text.strip():
        return None
    try:
        return Decimal(found.text.strip())
    except InvalidOperation as exc:
        raise Form13FParseError(f"bad decimal {found.text!r} at {tag}") from exc


def _txt(el, tag: str) -> str | None:
    found = el.find(f"{{*}}{tag}")
    return found.text.strip() if (found is not None and found.text) else None


def parse_13f(text: str) -> Filing13F:
    h = sgml.parse_header(text)
    if h.submission_type not in FORM_TYPES:
        raise Form13FParseError(f"unexpected submission type {h.submission_type!r}")
    if not h.filers or not h.filers[0].cik:
        raise Form13FParseError("no filer CIK in header")
    if h.period_of_report is None:
        raise Form13FParseError("no CONFORMED PERIOD OF REPORT in header")

    info = _find_information_table(text)
    if info is None:
        raise Form13FParseError("no informationTable (pre-2013 or malformed)")

    root = SafeET.fromstring(info)  # defused: DTD/entity expansion rejected
    filing = Filing13F(
        filer_cik=h.filers[0].cik,
        filer_name=h.filers[0].name or "",
        period_end=h.period_of_report,
        knowable_time=h.acceptance.replace(tzinfo=EASTERN),
    )
    for entry in root.findall(".//{*}infoTable"):
        cusip = _txt(entry, "cusip")
        amt = entry.find("{*}shrsOrPrnAmt")
        shares = _dec(amt, "sshPrnamt") if amt is not None else None
        share_type = (_txt(amt, "sshPrnamtType") if amt is not None else None) or "SH"
        value = _dec(entry, "value")
        if cusip is None or value is None:
            raise Form13FParseError("infoTable entry missing cusip or value")
        filing.holdings.append(Holding(
            cusip=cusip.strip().upper(),
            issuer_name=_txt(entry, "nameOfIssuer") or "",
            value_raw=value,
            shares=shares,
            share_type=share_type,
        ))
    if not filing.holdings:
        raise Form13FParseError("informationTable has no entries")
    return filing


def aggregate_holdings(filing: Filing13F) -> list[tuple[str, str, str, Decimal, Decimal | None]]:
    """Sum shares and value per (cusip, share_type). Returns tuples of
    (cusip, share_type, issuer_name, value_usd, shares)."""
    acc: dict[tuple[str, str], dict] = {}
    for hld in filing.holdings:
        key = (hld.cusip, hld.share_type)
        cell = acc.setdefault(key, {"name": hld.issuer_name, "value": Decimal(0), "shares": None})
        cell["value"] += normalize_value_usd(hld.value_raw, filing.knowable_time.date())
        if hld.shares is not None:
            cell["shares"] = (cell["shares"] or Decimal(0)) + hld.shares
    return [(cusip, st, c["name"], c["value"], c["shares"]) for (cusip, st), c in acc.items()]


def validate_holding(value_usd: Decimal, shares: Decimal | None) -> list[str]:
    reasons: list[str] = []
    if value_usd < 0:
        reasons.append(f"value {value_usd} negative")
    if shares is not None and shares < 0:
        reasons.append(f"shares {shares} negative")
    return reasons


def ingest_day(conn: psycopg.Connection, client: EdgarClient, day: date, limit: int | None = None) -> dict:
    counters = {"filings": 0, "holdings": 0, "skipped": 0, "rejected": 0}
    from .runner import master_index_url
    index = client.get(master_index_url(day))
    rows = form4.parse_master_index(index.content.decode("latin-1"), form_types=FORM_TYPES)
    if limit:
        rows = rows[:limit]
    log.info("day %s: %d Form 13F filings in index", day, len(rows))

    for row in rows:
        try:
            _ingest_filing(conn, client, row, counters)
            conn.commit()
        except Exception as exc:  # one bad filing must never kill the day
            conn.rollback()
            reject(conn, SOURCE, row.accession_no, f"{type(exc).__name__}: {exc}", counters)
            conn.commit()

    with conn.cursor() as cur:
        cur.execute("SELECT max(knowable_time) FROM fund_holdings")
        freshest = cur.fetchone()[0]
    update_health(conn, SOURCE, counters["holdings"], counters["rejected"], freshest)
    conn.commit()
    return counters


def _ingest_filing(conn: psycopg.Connection, client: EdgarClient, row: form4.IndexRow, counters: dict) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM raw_filings WHERE accession_no = %s", (row.accession_no,))
        if cur.fetchone():
            counters["skipped"] += 1
            return

    fetched = client.get(row.url)
    filing = parse_13f(fetched.content.decode("latin-1"))
    aggregated = aggregate_holdings(filing)

    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO raw_filings (source, accession_no, source_url, sha256, accepted_at, payload)
               VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (accession_no) DO NOTHING""",
            (SOURCE, row.accession_no, row.url, fetched.sha256, filing.knowable_time, fetched.content),
        )
        filer_entity = get_or_create_entity(cur, filing.filer_cik, filing.filer_name, "institution")
        for cusip, share_type, issuer_name, value_usd, shares in aggregated:
            problems = validate_holding(value_usd, shares)
            if problems:
                reject(conn, SOURCE, row.accession_no, f"cusip {cusip}: {'; '.join(problems)}", counters)
                continue
            # issuer_entity left NULL here; resolved later via resolve-cusips (never guessed)
            cur.execute(
                """INSERT INTO fund_holdings
                   (accession_no, filer_entity, period_end, knowable_time, cusip, issuer_name_raw,
                    value_usd, shares, share_type)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (accession_no, cusip, share_type) DO NOTHING""",
                (row.accession_no, filer_entity, filing.period_end, filing.knowable_time,
                 cusip, issuer_name, value_usd, shares, share_type),
            )
            counters["holdings"] += 1
    counters["filings"] += 1
