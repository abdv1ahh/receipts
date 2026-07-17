"""Shared parser for the EDGAR SGML submission header.

Every full-text EDGAR submission begins with a machine-structured SGML header giving the
authoritative facts we rely on: submission type, acceptance datetime (knowable_time),
period of report, SEC file number, and the SUBJECT COMPANY / FILED BY / FILER blocks that
name the parties with their CIKs. We parse only this header, never the free-form HTML
body, so no fact we publish is a guess (see docs/threat-models/schedule13.md).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime


class HeaderParseError(ValueError):
    pass


def norm_cik(raw: str | None) -> str | None:
    """Canonical CIK: digits with leading zeros stripped, matching Slice 1's convention
    (form4 stored issuer_cik as lstrip('0')) and company_tickers' integer cik_str."""
    if not raw:
        return None
    digits = raw.strip().lstrip("0")
    return digits or None


@dataclass(frozen=True)
class HeaderParty:
    cik: str | None
    name: str | None


@dataclass
class SubmissionHeader:
    accession_no: str | None
    submission_type: str | None
    acceptance: datetime          # US/Eastern, tz-naive as published; caller tags it
    period_of_report: date | None
    filed_as_of_date: date | None
    file_number: str | None
    subject_companies: list[HeaderParty] = field(default_factory=list)
    filers: list[HeaderParty] = field(default_factory=list)


# top-level party markers appear at column 0 of the header
_PARTY_LABEL = re.compile(r"^(SUBJECT COMPANY|FILED BY|FILER|REPORTING-OWNER|ISSUER):", re.M)


def _first(pattern: str, text: str) -> str | None:
    m = re.search(pattern, text)
    return m.group(1).strip() if m else None


def _yyyymmdd(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y%m%d").date()
    except ValueError:
        return None


def parse_header(text: str) -> SubmissionHeader:
    head = text.split("</SEC-HEADER>", 1)[0] if "</SEC-HEADER>" in text else text.split("<DOCUMENT>", 1)[0]

    m = re.search(r"<ACCEPTANCE-DATETIME>(\d{14})", head)
    if not m:
        raise HeaderParseError("missing ACCEPTANCE-DATETIME header")
    acceptance = datetime.strptime(m.group(1), "%Y%m%d%H%M%S")

    header = SubmissionHeader(
        accession_no=_first(r"ACCESSION NUMBER:\s*([0-9-]+)", head),
        submission_type=_first(r"CONFORMED SUBMISSION TYPE:\s*(.+)", head),
        acceptance=acceptance,
        period_of_report=_yyyymmdd(_first(r"CONFORMED PERIOD OF REPORT:\s*(\d{8})", head)),
        filed_as_of_date=_yyyymmdd(_first(r"FILED AS OF DATE:\s*(\d{8})", head)),
        file_number=_first(r"SEC FILE NUMBER:\s*([0-9-]+)", head),
    )

    markers = list(_PARTY_LABEL.finditer(head))
    for i, mk in enumerate(markers):
        start = mk.end()
        end = markers[i + 1].start() if i + 1 < len(markers) else len(head)
        section = head[start:end]
        # first COMPANY CONFORMED NAME is the current name; FORMER COMPANY uses a
        # different label ("FORMER CONFORMED NAME") so it is not picked up here.
        party = HeaderParty(
            cik=norm_cik(_first(r"CENTRAL INDEX KEY:\s*(\d+)", section)),
            name=_first(r"COMPANY CONFORMED NAME:\s*(.+)", section),
        )
        label = mk.group(1)
        if label == "SUBJECT COMPANY":
            header.subject_companies.append(party)
        elif label in ("FILED BY", "FILER"):
            header.filers.append(party)
    return header
