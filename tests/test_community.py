"""Offline tests for the community layer's pure logic: handle validation (format + reserved words)
and the trader leaderboard (ranks only sufficiently-sampled traders, by win rate then sample size,
never by a raw-return number). No network, no database."""
from tradeos import community as C


def test_normalize_handle_accepts_valid_and_rejects_bad():
    assert C.normalize_handle("Swing_Trader7") == "swing_trader7"
    assert C.normalize_handle("@Nova") == "nova"
    assert C.normalize_handle("ab") is None            # too short
    assert C.normalize_handle("has spaces") is None    # invalid char
    assert C.normalize_handle("waytoolonghandle_over20") is None
    assert C.normalize_handle("admin") is None         # reserved
    assert C.normalize_handle("official") is None       # reserved
    assert C.normalize_handle("") is None and C.normalize_handle(None) is None


def _row(handle, sufficient, win_rate, n, rr=2.0):
    return {"handle": handle, "summary": {"sufficient": sufficient, "win_rate": win_rate,
                                          "n_closed": n, "avg_reward_risk": rr}}


def test_leaderboard_excludes_insufficient_and_ranks_by_win_rate_then_n():
    rows = [
        _row("alpha", True, 0.62, 20),
        _row("bravo", True, 0.62, 40),      # same rate, more trades -> ranks above alpha
        _row("charlie", True, 0.71, 12),    # highest rate -> first
        _row("delta", False, 0.90, 3),      # tiny sample -> NOT ranked (honesty)
    ]
    board = C.trader_leaderboard(rows)
    assert [x["handle"] for x in board] == ["charlie", "bravo", "alpha"]
    assert "delta" not in [x["handle"] for x in board]      # cherry-picked small sample can't game it
    assert board[0]["win_rate"] == 0.71 and board[0]["n_closed"] == 12


def test_leaderboard_empty_when_nobody_qualifies():
    assert C.trader_leaderboard([_row("x", False, 1.0, 2)]) == []
