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


def test_short_interest_flag_defaults_off_and_can_be_turned_on(monkeypatch):
    """ENABLE_CONGRESS was removed in migration 033 — it gated a source that was never built.
    ENABLE_SHORT_INTEREST stays: the data is ingested and parked against a future scoring version,
    which the owner confirmed on 2026-07-26 (docs/dead_code.md A-01)."""
    monkeypatch.delenv("ENABLE_SHORT_INTEREST", raising=False)
    assert config.short_interest_enabled() is False
    monkeypatch.setenv("ENABLE_SHORT_INTEREST", "true")
    assert config.short_interest_enabled() is True
    assert not hasattr(config, "congress_enabled")
