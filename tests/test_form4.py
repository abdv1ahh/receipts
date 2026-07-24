from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from tradeos.ingestion import form4
from tradeos.ingestion.edgar_client import EdgarClient

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> str:
    return (FIXTURES / name).read_text()


# ------------------------------------------------------------------ master index

def test_master_index_filters_form4_and_amendments():
    rows = form4.parse_master_index(load("master_sample.idx"))
    assert [r.form_type for r in rows] == ["4", "4/A"]
    assert rows[0].cik == "42"
    assert rows[0].url == "https://www.sec.gov/Archives/edgar/data/42/0000000001-26-000123.txt"
    assert rows[0].accession_no == "0000000001-26-000123"


def test_master_index_ignores_header_junk():
    assert form4.parse_master_index("random|garbage|lines\nno pipes at all") == []


# --------------------------------------------------------------- submission split

def test_split_submission_extracts_acceptance_and_xml():
    accepted, xml = form4.split_submission(load("form4_submission.txt"))
    assert accepted == datetime(2026, 7, 10, 16, 30, 45)
    assert "<ownershipDocument>" in xml


def test_split_submission_rejects_missing_header():
    with pytest.raises(form4.SubmissionParseError):
        form4.split_submission("<XML><ownershipDocument/></XML>")


# ------------------------------------------------------------------- form 4 XML

def test_parse_form4_fields():
    _, xml = form4.split_submission(load("form4_submission.txt"))
    f = form4.parse_form4_xml(xml)
    assert f.issuer_cik == "42"
    assert f.issuer_name == "TESTFIXTURE CORP"
    assert f.symbol == "TFIX"
    assert len(f.owners) == 1
    owner = f.owners[0]
    assert owner.cik == "777"
    assert owner.is_director and owner.is_officer
    assert owner.officer_title == "Chief Executive Officer"
    assert len(f.transactions) == 2
    buy, sell = f.transactions
    assert buy.transaction_code == "P"
    assert buy.event_time == date(2026, 7, 8)
    assert buy.shares == Decimal("15000")
    assert buy.price_per_share == Decimal("23.41")
    assert buy.acquired_disposed == "A"
    assert buy.shares_after == Decimal("215000")
    assert sell.acquired_disposed == "D"


def test_parse_tolerates_timezone_suffixed_transaction_date():
    """Real filers sometimes append a tz offset to transactionDate; take the date part."""
    xml = (
        "<ownershipDocument><issuer><issuerCik>42</issuerCik>"
        "<issuerName>TESTFIXTURE CORP</issuerName></issuer>"
        "<reportingOwner><reportingOwnerId><rptOwnerCik>777</rptOwnerCik>"
        "<rptOwnerName>DOE JANE</rptOwnerName></reportingOwnerId></reportingOwner>"
        "<nonDerivativeTable><nonDerivativeTransaction>"
        "<securityTitle><value>Common Stock</value></securityTitle>"
        "<transactionDate><value>2026-07-13-05:00</value></transactionDate>"
        "<transactionCoding><transactionCode>P</transactionCode></transactionCoding>"
        "<transactionAmounts>"
        "<transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>"
        "</transactionAmounts>"
        "</nonDerivativeTransaction></nonDerivativeTable></ownershipDocument>"
    )
    f = form4.parse_form4_xml(xml)
    assert f.transactions[0].event_time == date(2026, 7, 13)


def test_parse_rejects_external_entities():
    """XXE must die at the parser. defusedxml raises on DTDs."""
    evil = (
        '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
        "<ownershipDocument><issuer><issuerCik>1</issuerCik>"
        "<issuerName>&xxe;</issuerName></issuer></ownershipDocument>"
    )
    with pytest.raises(Exception):
        form4.parse_form4_xml(evil)


def test_parse_rejects_missing_issuer():
    with pytest.raises(form4.SubmissionParseError):
        form4.parse_form4_xml("<ownershipDocument></ownershipDocument>")


# ------------------------------------------------------------------ validation

def _txn(**overrides) -> form4.Transaction:
    base = dict(
        seq=1, security_title="Common Stock", event_time=date(2026, 7, 8),
        transaction_code="P", shares=Decimal("100"), price_per_share=Decimal("10"),
        acquired_disposed="A", shares_after=Decimal("1000"), direct_indirect="D",
    )
    base.update(overrides)
    return form4.Transaction(**base)


TODAY = date(2026, 7, 15)


def test_validation_passes_sane_transaction():
    assert form4.validate_transaction(_txn(), TODAY) == []


def test_validation_rejects_future_event_time():
    reasons = form4.validate_transaction(_txn(event_time=date(2026, 8, 1)), TODAY)
    assert any("future" in r for r in reasons)


def test_validation_rejects_absurd_price_and_negative_shares():
    reasons = form4.validate_transaction(
        _txn(price_per_share=Decimal("5000000"), shares=Decimal("-5")), TODAY
    )
    assert len(reasons) == 2


def test_validation_rejects_bad_acquired_disposed():
    reasons = form4.validate_transaction(_txn(acquired_disposed="X"), TODAY)
    assert any("acquired_disposed" in r for r in reasons)


# ---------------------------------------------------------------- client safety

def test_client_refuses_hosts_outside_allowlist():
    client = EdgarClient("TradeOSS test@example.com")
    with pytest.raises(ValueError):
        client.get("https://evil.example.com/edgar/data/1/1.txt")
    with pytest.raises(ValueError):
        client.get("http://www.sec.gov/insecure")  # https only
    client.close()


def test_client_requires_contact_in_user_agent():
    with pytest.raises(ValueError):
        EdgarClient("no-contact-here")
