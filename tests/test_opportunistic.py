"""The CMP routine/opportunistic split — the four cases that decide the label.

Offline and pure: `classify_insider` takes dates and returns a string, so every case here is a
fixed calendar with no database and no clock. The cases are the ones that actually separate the
three answers — an exact three-year run, a run with one year missing, a record too short to
judge, and no record at all — plus the two boundary behaviours that would silently corrupt a
point-in-time replay if they broke.
"""
from datetime import date

from tradeos.signals.opportunistic import (
    OPPORTUNISTIC,
    ROUTINE,
    UNCLASSIFIED,
    classify_insider,
    counts_toward_gate,
)


def test_exactly_three_years_same_month_is_routine():
    """A March trade in each of the three preceding years is the textbook routine trader."""
    history = [date(2023, 3, 14), date(2024, 3, 2), date(2025, 3, 19)]
    assert classify_insider(history, date(2026, 3, 10)) == ROUTINE


def test_gap_in_the_sequence_is_opportunistic():
    """Deep enough history to judge, but 2024 has no March trade — the schedule is broken."""
    history = [date(2023, 3, 14), date(2024, 7, 2), date(2025, 3, 19)]
    assert classify_insider(history, date(2026, 3, 10)) == OPPORTUNISTIC


def test_two_years_of_history_is_unclassified_never_routine():
    """Same month two years running, but the window is not covered.

    This is the case the rule exists to protect: 2024 and 2025 both hold March, so a naive
    "did they trade this month before?" test would call it routine on an insider whose record
    only starts in 2024. An absent record is not evidence of a schedule.
    """
    history = [date(2024, 3, 2), date(2025, 3, 19)]
    assert classify_insider(history, date(2026, 3, 10)) == UNCLASSIFIED


def test_first_ever_trade_is_unclassified():
    assert classify_insider([], date(2026, 3, 10)) == UNCLASSIFIED


def test_history_depth_is_counted_in_months_not_days():
    """Deviation 3: 2023-03-28 is 1,069 days before 2026-03-20 — under three years by day
    count — but it holds the (Y-3, March) slot the rule asks about. Counting days here would
    return UNCLASSIFIED for a calendar the month test calls ROUTINE."""
    history = [date(2023, 3, 28), date(2024, 3, 2), date(2025, 3, 19)]
    assert classify_insider(history, date(2026, 3, 20)) == ROUTINE


def test_the_trade_being_classified_never_classifies_itself():
    """Dates on or after `as_of` are dropped. Without this a caller passing an unfiltered
    history would let the trade's own date fill one of the three slots, and a point-in-time
    replay would be reading the present."""
    history = [date(2023, 3, 14), date(2024, 3, 2), date(2025, 3, 19), date(2026, 3, 10),
               date(2026, 8, 1)]
    assert classify_insider(history, date(2026, 3, 10)) == ROUTINE
    # and with the run one year short, the future trades cannot rescue it
    assert classify_insider([date(2025, 3, 19), date(2026, 3, 10)], date(2026, 3, 10)) == UNCLASSIFIED


def test_only_routine_is_kept_out_of_the_gate():
    """Unclassified counts as a voice: on this dataset it is almost every insider, and
    treating "cannot tell" as "scheduled" would empty the signal rather than measure it."""
    assert counts_toward_gate(OPPORTUNISTIC) is True
    assert counts_toward_gate(UNCLASSIFIED) is True
    assert counts_toward_gate(ROUTINE) is False
