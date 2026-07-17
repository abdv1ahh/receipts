"""Slice 5 offline tests for short-interest helpers: the business-day publication lag and the
modular-input config flags (convergence must survive their default-off state)."""
from datetime import date

from tradeos import config
from tradeos.ingestion.finra import _add_business_days


def test_add_business_days_skips_weekends():
    # Friday 2026-05-15 + 1 business day -> Monday 2026-05-18
    assert _add_business_days(date(2026, 5, 15), 1) == date(2026, 5, 18)
    # +8 business days from a mid-month Friday lands two weeks out, weekends skipped
    assert _add_business_days(date(2026, 5, 15), 8) == date(2026, 5, 27)


def test_modular_flags_default_off(monkeypatch):
    monkeypatch.delenv("ENABLE_CONGRESS", raising=False)
    monkeypatch.delenv("ENABLE_SHORT_INTEREST", raising=False)
    assert config.congress_enabled() is False
    assert config.short_interest_enabled() is False
    monkeypatch.setenv("ENABLE_SHORT_INTEREST", "true")
    assert config.short_interest_enabled() is True
