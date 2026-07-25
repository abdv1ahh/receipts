"""Slice 4 offline tests for the backtest math: exact forward/excess returns on frozen
synthetic price paths (clearly-fictional test fixtures), horizon-not-closed handling,
episode de-duplication, and the calibration insufficient-sample rule. No network, no DB.
"""
from datetime import date, timedelta

from tradeos.backtest.engine import (
    Series,
    bucket_calibration,
    excess_return,
    group_episodes,
    wilson_interval,
)


def _bdays(start: date, end: date) -> list[date]:
    d, out = start, []
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _series(days, fn) -> Series:
    return Series.from_rows([(d, fn(d)) for d in days])


DAYS = _bdays(date(2025, 1, 1), date(2025, 7, 1))
STEP = date(2025, 2, 3)  # first trading day on/after (2025-01-02 entry + 30 calendar days)


def test_excess_return_exact():
    # symbol +10% by the 30-day exit, SPY +5% -> excess = +5.00%
    sym = _series(DAYS, lambda d: 110.0 if d >= STEP else 100.0)
    spy = _series(DAYS, lambda d: 210.0 if d >= STEP else 200.0)
    val, reason = excess_return(sym, spy, date(2025, 1, 1), 30)
    assert reason == "ok"
    assert val == 0.05


def test_entry_is_first_trading_day_after_as_of():
    # as_of on a Friday -> entry must be the following Monday (no weekend look-through)
    sym = _series(DAYS, lambda d: 110.0 if d >= STEP else 100.0)
    spy = _series(DAYS, lambda d: 210.0 if d >= STEP else 200.0)
    friday = date(2025, 1, 3)
    val, reason = excess_return(sym, spy, friday, 30)
    assert reason == "ok"  # entry Monday 2025-01-06, both sides resolve


def test_open_horizon_returns_none():
    sym = _series(DAYS, lambda d: 100.0)
    spy = _series(DAYS, lambda d: 100.0)
    # as_of near the end of the price history: the 30-day window has not closed
    val, reason = excess_return(sym, spy, date(2025, 6, 30), 30)
    assert val is None and reason == "horizon_open_or_delisted"


def test_episode_dedup_by_14_day_gap():
    d0 = date(2025, 3, 3)
    clusters = [
        (d0, 1, "high"),
        (d0 + timedelta(days=5), 2, "high"),    # same episode (gap 5)
        (d0 + timedelta(days=30), 3, "medium"),  # new episode (gap 25 > 14)
        (d0 + timedelta(days=31), 4, "medium"),
    ]
    eps = group_episodes(clusters, gap_days=14)
    assert len(eps) == 2
    assert [e[0][1] for e in eps] == [1, 3]       # entered at the first cluster of each episode


def test_calibration_insufficient_sample():
    small = bucket_calibration([0.02, -0.01, 0.03, 0.05, -0.04])  # 5 episodes, 3 hits
    assert small["episodes"] == 5
    assert small["sufficient"] is False           # < 30 -> never shown as a rate
    assert small["hit_rate"] == 0.6
    assert small["ci95"] is not None
    empty = bucket_calibration([])
    assert empty["episodes"] == 0 and empty["hit_rate"] is None


def test_wilson_interval_bounds():
    lo, hi = wilson_interval(21, 30)
    assert 0.0 <= lo <= hi <= 1.0
    assert wilson_interval(0, 0) is None
