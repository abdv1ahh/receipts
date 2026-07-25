"""Slice 2 offline tests: SGML header parsing, 13D/G and 13F parsers, value normalization,
within-filing aggregation, validation, and XXE safety. No network, no database — fixtures
are clearly fictional (TESTFIXTURE) and never enter the runtime DB."""
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from defusedxml.common import EntitiesForbidden

from tradeos.ingestion import form4, form13f, schedule13, sgml

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> str:
    return (FIXTURES / name).read_text()


# ----------------------------------------------------------------- SGML header

def test_norm_cik_strips_leading_zeros():
    assert sgml.norm_cik("0000000042") == "42"
    assert sgml.norm_cik("42") == "42"
    assert sgml.norm_cik("") is None
    assert sgml.norm_cik(None) is None


def test_header_parses_subject_and_filer_blocks():
    h = sgml.parse_header(load("schedule13d_submission.txt"))
    assert h.submission_type == "SCHEDULE 13D"
    assert h.accession_no == "0000000555-26-000042"
    assert h.acceptance == datetime(2026, 7, 10, 15, 0, 0)
    assert h.period_of_report == date(2026, 7, 1)
    assert h.file_number == "005-99999"
    assert [s.cik for s in h.subject_companies] == ["42"]
    assert h.subject_companies[0].name == "TESTFIXTURE CORP"
    assert [f.cik for f in h.filers] == ["555"]
    assert h.filers[0].name == "TESTFIXTURE CAPITAL LP"


def test_header_rejects_missing_acceptance():
    with pytest.raises(sgml.HeaderParseError):
        sgml.parse_header("CONFORMED SUBMISSION TYPE: SCHEDULE 13D\n</SEC-HEADER>")


# ------------------------------------------------------------ master index filter

def test_master_index_filters_schedule13_labels():
    rows = form4.parse_master_index(load("master_13_sample.idx"), form_types=schedule13.FORM_TYPES)
    assert [r.form_type for r in rows] == ["SCHEDULE 13D", "SCHEDULE 13G", "SCHEDULE 13D/A", "SCHEDULE 13G/A"]
    # the Form 4 and 13F rows in the same index are excluded
    assert all("13F" not in r.form_type and r.form_type != "4" for r in rows)


def test_master_index_filters_13f_labels():
    rows = form4.parse_master_index(load("master_13_sample.idx"), form_types=form13f.FORM_TYPES)
    assert [r.form_type for r in rows] == ["13F-HR", "13F-HR/A"]


# ------------------------------------------------------------------ 13D/G parse

def test_parse_stake_fields_and_confidence():
    rec = schedule13.parse_stake(load("schedule13d_submission.txt"))
    assert rec.form_type == "SCHEDULE 13D"
    assert rec.activist is True
    assert rec.is_amendment is False
    assert rec.filer_cik == "555" and rec.issuer_cik == "42"
    assert rec.issuer_name == "TESTFIXTURE CORP"
    assert rec.file_number == "005-99999"
    # header carried CONFORMED PERIOD OF REPORT, so event_time is high-confidence
    assert rec.event_time == date(2026, 7, 1)
    assert rec.parse_confidence == "header_period"
    # never scrape the HTML cover page: percent stays unknown at the record level
    assert not hasattr(rec, "percent_owned") or getattr(rec, "percent_owned", None) is None


def test_parse_stake_falls_back_to_filing_date_when_no_period():
    text = load("schedule13d_submission.txt").replace("CONFORMED PERIOD OF REPORT:\t20260701\n", "")
    rec = schedule13.parse_stake(text)
    assert rec.event_time == date(2026, 7, 10)          # FILED AS OF DATE
    assert rec.parse_confidence == "filing_date_fallback"


def test_validate_stake_flags_future_and_missing():
    rec = schedule13.parse_stake(load("schedule13d_submission.txt"))
    good = schedule13.validate_stake(rec, date(2026, 7, 15))
    assert good == []
    future = schedule13.validate_stake(rec, date(2026, 6, 1))
    assert any("future" in r for r in future)


# ------------------------------------------------------------------- 13F parse

def test_parse_13f_reads_namespaced_information_table():
    f = form13f.parse_13f(load("form13f_submission.txt"))
    assert f.filer_cik == "900"
    assert f.filer_name == "TESTFIXTURE ADVISORS LLC"
    assert f.period_end == date(2026, 6, 30)
    assert f.knowable_time.date() == date(2026, 7, 14)
    # three raw infoTable rows (two share one CUSIP)
    assert len(f.holdings) == 3
    assert {h.cusip for h in f.holdings} == {"00000E101", "00000T202"}


def test_aggregate_holdings_sums_duplicate_cusip_rows():
    f = form13f.parse_13f(load("form13f_submission.txt"))
    agg = {(c, st): (name, val, sh) for c, st, name, val, sh in form13f.aggregate_holdings(f)}
    # the two TESTFIXTURE CORP rows (value 1000+2000, shares 10+20) collapse to one total
    name, value, shares = agg[("00000E101", "SH")]
    assert value == Decimal("3000")
    assert shares == Decimal("30")
    # the distinct issuer is untouched
    _, value2, shares2 = agg[("00000T202", "SH")]
    assert value2 == Decimal("500") and shares2 == Decimal("5")


def test_normalize_value_thousands_before_2023_whole_after():
    # pre-amendment filing reported thousands: normalize by x1000
    assert form13f.normalize_value_usd(Decimal("234"), date(2022, 6, 30)) == Decimal("234000")
    # post-amendment filing reported whole USD: unchanged
    assert form13f.normalize_value_usd(Decimal("234446"), date(2026, 7, 14)) == Decimal("234446")


def test_13f_parser_rejects_external_entities():
    """XXE must die at the parser here too. defusedxml raises on DTDs."""
    header = (
        "<ACCEPTANCE-DATETIME>20260714094929\n"
        "CONFORMED SUBMISSION TYPE:\t13F-HR\n"
        "CONFORMED PERIOD OF REPORT:\t20260630\n"
        "FILER:\n\tCOMPANY DATA:\n"
        "\t\tCOMPANY CONFORMED NAME:\t\t\tTESTFIXTURE ADVISORS LLC\n"
        "\t\tCENTRAL INDEX KEY:\t\t\t0000000900\n"
        "</SEC-HEADER>\n"
    )
    evil = (
        '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
        '<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">'
        "<infoTable><nameOfIssuer>&xxe;</nameOfIssuer><cusip>00000E101</cusip>"
        "<value>1</value></infoTable></informationTable>"
    )
    text = header + "<DOCUMENT><XML>" + evil + "</XML></DOCUMENT>"
    # Assert the SPECIFIC defence fired — see the note in test_form4.py.
    with pytest.raises(EntitiesForbidden):
        form13f.parse_13f(text)


def test_13f_parser_rejects_filing_without_information_table():
    text = (
        "<ACCEPTANCE-DATETIME>20260714094929\n"
        "CONFORMED SUBMISSION TYPE:\t13F-HR\n"
        "CONFORMED PERIOD OF REPORT:\t20260630\n"
        "FILER:\n\tCOMPANY DATA:\n"
        "\t\tCOMPANY CONFORMED NAME:\t\t\tTESTFIXTURE ADVISORS LLC\n"
        "\t\tCENTRAL INDEX KEY:\t\t\t0000000900\n</SEC-HEADER>\n"
    )
    with pytest.raises(form13f.Form13FParseError):
        form13f.parse_13f(text)


def test_price_row_rejects_high_below_low():
    """Guards the OHLC sanity check. This path had no test, which is how a variable rename
    silently broke it (the reference to the old name only failed at runtime)."""
    from datetime import date

    from tradeos.ingestion.prices import _valid_row
    today = date(2026, 7, 25)
    good = {"date": "2026-07-24", "adjOpen": 10, "adjHigh": 12, "adjLow": 9, "adjClose": 11, "adjVolume": 100}
    assert _valid_row(good, today) == (date(2026, 7, 24), 10, 12, 9, 11, 100)
    assert _valid_row({**good, "adjHigh": 8, "adjLow": 9}, today) is None      # high < low -> reject
    assert _valid_row({**good, "adjClose": 0}, today) is None                  # non-positive close
    assert _valid_row({**good, "date": "2026-07-26"}, today) is None           # future bar
