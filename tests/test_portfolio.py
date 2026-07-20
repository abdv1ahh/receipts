"""Offline tests for paper-portfolio P&L: return vs SPY over the real holding window, honest
'pending' when a name can't be priced, and equal-weight aggregation that never averages in a
guess for an unpriced position. No network, no database."""
from datetime import date

from tradeos import portfolio as pf
from tradeos.backtest.engine import Series


def _series(pairs):
    return Series.from_rows([(date.fromisoformat(d), c) for d, c in pairs])


def test_position_pnl_excess_vs_spy():
    sym = _series([("2026-01-05", 100.0), ("2026-02-05", 110.0)])
    spy = _series([("2026-01-05", 400.0), ("2026-02-05", 420.0)])
    p = pf.position_pnl(sym, spy, date(2026, 1, 1))
    assert p["priced"] is True
    assert p["entry_day"] == "2026-01-05" and p["entry_price"] == 100.0
    assert p["return"] == 0.1                      # 100 -> 110
    assert p["spy_return"] == 0.05                 # 400 -> 420
    assert p["excess"] == 0.05
    assert p["days_held"] == 31


def test_position_pnl_pending_when_unpriceable():
    spy = _series([("2026-01-05", 400.0), ("2026-02-05", 420.0)])
    assert pf.position_pnl(_series([]), spy, date(2026, 1, 1)) == {"priced": False}
    one_day = _series([("2026-01-05", 100.0)])     # no later day -> no holding window
    assert pf.position_pnl(one_day, spy, date(2026, 1, 1)) == {"priced": False}


def test_summarize_excludes_pending_from_averages():
    positions = [
        {"priced": True, "return": 0.10, "spy_return": 0.05, "excess": 0.05},
        {"priced": True, "return": -0.02, "spy_return": 0.01, "excess": -0.03},
        {"priced": False},
    ]
    s = pf.summarize(positions)
    assert s["positions"] == 3 and s["priced"] == 2 and s["pending"] == 1
    assert s["avg_return"] == 0.04 and s["spy_return"] == 0.03
    assert s["avg_excess"] == 0.01                 # not diluted by the pending name
    assert s["beat_spy"] == 1


def test_summarize_all_pending_is_honest_nulls():
    s = pf.summarize([{"priced": False}, {"priced": False}])
    assert s["priced"] == 0 and s["avg_return"] is None and s["avg_excess"] is None
