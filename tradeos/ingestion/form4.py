"""Form 4 pipeline: parse EDGAR daily master index, split full-text submissions,
parse ownershipDocument XML, validate.

Point-in-time discipline:
- event_time  = transactionDate inside the filing (when the insider actually traded)
- knowable_time = ACCEPTANCE-DATETIME from the EDGAR submission header
  (when the filing became publicly knowable)
Backtests may only ever query through knowable_time.

XML is parsed with defusedxml: external entities and DTDs are rejected, closing XXE.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from defusedxml import ElementTree as SafeET

FORM_TYPES = {"4", "4/A"}

# ---------------------------------------------------------------- master index

@dataclass(frozen=True)
class IndexRow:
    cik: str
    company: str
    form_type: str
    date_filed: str
    filename: str  # e.g. edgar/data/320193/0000320193-26-000042.txt

    @property
    def url(self) -> str:
        return f"https://www.sec.gov/Archives/{self.filename}"

    @property
    def accession_no(self) -> str:
        m = re.search(r"(\d{10}-\d{2}-\d{6})", self.filename)
        if not m:
            raise ValueError(f"no accession number in {self.filename}")
        return m.group(1)


def parse_master_index(text: str, form_types: set[str] = FORM_TYPES) -> list[IndexRow]:
    """master.idx is pipe-delimited: CIK|Company Name|Form Type|Date Filed|Filename."""
    rows: list[IndexRow] = []
    for line in text.splitlines():
        parts = line.split("|")
        if len(parts) != 5 or not parts[0].strip().isdigit():
            continue  # header, separator, or junk lines
        cik, company, form_type, date_filed, filename = (p.strip() for p in parts)
        if form_type in form_types:
            rows.append(IndexRow(cik, company, form_type, date_filed, filename))
    return rows


# ------------------------------------------------------------- submission split

class SubmissionParseError(ValueError):
    pass


def split_submission(text: str) -> tuple[datetime, str]:
    """From a full-text EDGAR submission, extract (acceptance datetime UTC-naive as
    published, ownershipDocument XML string)."""
    m = re.search(r"<ACCEPTANCE-DATETIME>(\d{14})", text)
    if not m:
        raise SubmissionParseError("missing ACCEPTANCE-DATETIME header")
    # EDGAR acceptance timestamps are US Eastern; we store them tagged as such at the
    # DB boundary. Here we parse the raw digits.
    accepted = datetime.strptime(m.group(1), "%Y%m%d%H%M%S")

    xml_m = re.search(r"<XML>\s*(.*?)\s*</XML>", text, re.DOTALL)
    if not xml_m:
        raise SubmissionParseError("no <XML> block in submission")
    xml = xml_m.group(1)
    if "<ownershipDocument" not in xml:
        raise SubmissionParseError("first XML block is not an ownershipDocument")
    return accepted, xml


# ----------------------------------------------------------------- form 4 XML

@dataclass
class Owner:
    cik: str
    name: str
    is_director: bool
    is_officer: bool
    officer_title: str | None


@dataclass
class Transaction:
    seq: int
    security_title: str
    event_time: date
    transaction_code: str
    shares: Decimal | None
    price_per_share: Decimal | None
    acquired_disposed: str  # 'A' or 'D'
    shares_after: Decimal | None
    direct_indirect: str | None  # 'D' or 'I'


@dataclass
class Form4Filing:
    issuer_cik: str
    issuer_name: str
    symbol: str | None
    owners: list[Owner] = field(default_factory=list)
    transactions: list[Transaction] = field(default_factory=list)


def _text(el, path: str) -> str | None:
    found = el.find(path)
    if found is None or found.text is None:
        return None
    return found.text.strip() or None


def _decimal(el, path: str) -> Decimal | None:
    raw = _text(el, path)
    if raw is None:
        return None
    try:
        return Decimal(raw)
    except InvalidOperation as exc:
        raise SubmissionParseError(f"bad decimal {raw!r} at {path}") from exc


def _flag(el, path: str) -> bool:
    return (_text(el, path) or "").strip() in {"1", "true"}


def _event_date(raw: str) -> date:
    """Some filers append a timezone offset or time to transactionDate
    (e.g. '2026-07-13-05:00'), which date.fromisoformat rejects. Take the date portion."""
    m = re.match(r"\s*(\d{4}-\d{2}-\d{2})", raw)
    if not m:
        raise SubmissionParseError(f"unparseable transaction date {raw!r}")
    return date.fromisoformat(m.group(1))


def parse_form4_xml(xml: str) -> Form4Filing:
    root = SafeET.fromstring(xml)  # defused: DTD/entity expansion rejected

    issuer = root.find("issuer")
    if issuer is None:
        raise SubmissionParseError("missing issuer block")
    filing = Form4Filing(
        issuer_cik=(_text(issuer, "issuerCik") or "").lstrip("0") or "0",
        issuer_name=_text(issuer, "issuerName") or "",
        symbol=_text(issuer, "issuerTradingSymbol"),
    )
    if not filing.issuer_cik or not filing.issuer_name:
        raise SubmissionParseError("issuer CIK or name missing")

    for ro in root.findall("reportingOwner"):
        rid = ro.find("reportingOwnerId")
        rel = ro.find("reportingOwnerRelationship")
        if rid is None:
            raise SubmissionParseError("reportingOwner without reportingOwnerId")
        filing.owners.append(Owner(
            cik=(_text(rid, "rptOwnerCik") or "").lstrip("0") or "0",
            name=_text(rid, "rptOwnerName") or "",
            is_director=_flag(rel, "isDirector") if rel is not None else False,
            is_officer=_flag(rel, "isOfficer") if rel is not None else False,
            officer_title=_text(rel, "officerTitle") if rel is not None else None,
        ))
    if not filing.owners:
        raise SubmissionParseError("no reporting owners")

    table = root.find("nonDerivativeTable")
    txns = table.findall("nonDerivativeTransaction") if table is not None else []
    for seq, txn in enumerate(txns, start=1):
        raw_date = _text(txn, "transactionDate/value")
        if raw_date is None:
            raise SubmissionParseError(f"transaction {seq} missing date")
        filing.transactions.append(Transaction(
            seq=seq,
            security_title=_text(txn, "securityTitle/value") or "",
            event_time=_event_date(raw_date),
            transaction_code=_text(txn, "transactionCoding/transactionCode") or "",
            shares=_decimal(txn, "transactionAmounts/transactionShares/value"),
            price_per_share=_decimal(txn, "transactionAmounts/transactionPricePerShare/value"),
            acquired_disposed=_text(txn, "transactionAmounts/transactionAcquiredDisposedCode/value") or "",
            shares_after=_decimal(txn, "postTransactionAmounts/sharesOwnedFollowingTransaction/value"),
            direct_indirect=_text(txn, "ownershipNature/directOrIndirectOwnership/value"),
        ))
    return filing


# ------------------------------------------------------------------ validation

MAX_PRICE = Decimal("1000000")      # no US-listed share trades near this; beyond it is corrupt data
MAX_SHARES = Decimal("10000000000")  # ten billion shares in one insider trade is corrupt data


def validate_transaction(t: Transaction, today: date) -> list[str]:
    """Range and sanity checks. A rejected transaction goes to ingest_rejects with these
    reasons and never reaches signal computation. Loud, not silent."""
    reasons: list[str] = []
    if t.event_time > today:
        reasons.append(f"event_time {t.event_time} is in the future")
    if t.event_time.year < 1994:
        reasons.append(f"event_time {t.event_time} predates EDGAR")
    if t.shares is not None and (t.shares < 0 or t.shares > MAX_SHARES):
        reasons.append(f"shares {t.shares} out of range")
    if t.price_per_share is not None and (t.price_per_share < 0 or t.price_per_share > MAX_PRICE):
        reasons.append(f"price {t.price_per_share} out of range")
    if t.acquired_disposed not in {"A", "D"}:
        reasons.append(f"acquired_disposed {t.acquired_disposed!r} invalid")
    if not t.transaction_code:
        reasons.append("missing transaction code")
    return reasons
