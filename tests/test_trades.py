"""Offline tests for the trade journal engine: reward:risk and realized P&L math, the guard-safe
analyzer, honest small-sample performance analytics, and — the compliance invariant — that every
string the analyzer or performance summary can emit clears the directive guard (no advice). No
network, no database."""
from datetime import date

from tradeos import trades as T
from tradeos.explain.guards import directive_guard


# ------------------------------------------------------------------ pure math

def test_reward_risk_long_and_short():
    assert T.reward_risk(100, 90, 130, "long") == 3.0        # risk 10, reward 30
    assert T.reward_risk(100, 110, 70, "short") == 3.0       # risk 10, reward 30
    assert T.reward_risk(100, 90, 115, "long") == 1.5        # risk 10, reward 15


def test_reward_risk_none_on_bad_or_missing_levels():
    assert T.reward_risk(100, None, 130) is None             # missing stop
    assert T.reward_risk(100, 110, 130, "long") is None      # stop above entry on a long -> risk<=0
    assert T.reward_risk(100, 90, 95, "short") is None       # target above entry on a short -> reward<=0


def test_realized_pnl_long_and_short():
    assert T.realized_pnl_pct(100, 110, "long") == 0.1
    assert T.realized_pnl_pct(100, 90, "long") == -0.1
    assert T.realized_pnl_pct(100, 90, "short") == 0.1       # short profits when price falls
    assert T.realized_pnl_pct(0, 90) is None and T.realized_pnl_pct(100, None) is None


# ------------------------------------------------------------------ analyzer

def test_analyze_reports_reward_risk_and_result():
    a = T.analyze_trade({"symbol": "NVDA", "direction": "long", "status": "closed",
                         "entry_price": 100, "stop_price": 90, "target_price": 130,
                         "exit_price": 118, "size": 50, "size_unit": "shares", "confidence": 3})
    assert a["reward_risk"] == 3.0
    assert a["realized_pnl_pct"] == 0.18
    assert any("reward-to-risk is 3.0 to 1" in s for s in a["observations"])
    assert any("18.0% gain" in s for s in a["observations"])
    assert any("risks about 500" in s and "to the stop" in s for s in a["observations"])


def test_analyze_flags_missing_stop_and_sub_one_rr():
    no_stop = T.analyze_trade({"symbol": "AAPL", "direction": "long", "status": "open",
                               "entry_price": 100, "target_price": 120})
    assert any("No stop level" in s for s in no_stop["risk_flags"])
    weak = T.analyze_trade({"symbol": "AAPL", "direction": "long", "status": "open",
                            "entry_price": 100, "stop_price": 80, "target_price": 110})
    assert weak["reward_risk"] == 0.5
    assert any("below 1 to 1" in s for s in weak["risk_flags"])


def test_analyze_high_conviction_loss_is_descriptive_not_a_verdict():
    a = T.analyze_trade({"symbol": "TSLA", "direction": "long", "status": "closed",
                         "entry_price": 100, "exit_price": 90, "confidence": 5})
    assert any("high conviction (5 of 5)" in s and "loss" in s for s in a["observations"])


def test_analyze_timeframe_mismatch_flag():
    a = T.analyze_trade({"symbol": "SPY", "direction": "long", "status": "closed",
                         "entry_price": 100, "exit_price": 101, "timeframe": "day",
                         "opened_on": date(2026, 1, 5), "closed_on": date(2026, 1, 12)})
    assert any("Tagged as a day trade but held 7 days" in s for s in a["risk_flags"])


def test_analyze_smart_money_cross_reference_is_context_only():
    a = T.analyze_trade({"symbol": "NVDA", "direction": "long", "status": "open", "entry_price": 100},
                        signal_context={"bucket": "high", "voices": 4, "as_of": "2026-01-15T00:00:00"})
    assert len(a["context"]) == 1
    assert "high-confidence smart-money convergence in NVDA across 4 independent filers" in a["context"][0]
    assert "context only" in a["context"][0]


def test_every_analyzer_and_prose_string_clears_the_directive_guard():
    """Compliance invariant: nothing the analyzer or its prose emits may read as advice."""
    fixtures = [
        {"symbol": "NVDA", "direction": "long", "status": "closed", "entry_price": 100,
         "stop_price": 90, "target_price": 130, "exit_price": 118, "size": 50, "size_unit": "shares",
         "confidence": 5, "timeframe": "day", "opened_on": date(2026, 1, 5), "closed_on": date(2026, 1, 9)},
        {"symbol": "AAPL", "direction": "short", "status": "open", "entry_price": 100, "target_price": 120},
        {"symbol": "GME", "direction": "long", "status": "closed", "entry_price": 50, "exit_price": 40,
         "confidence": 1, "stop_price": 45, "target_price": 80, "size": 10, "size_unit": "shares"},
        {"symbol": None, "direction": "long", "status": "planned"},
    ]
    ctx = {"bucket": "medium", "voices": 3, "as_of": "2026-02-01T00:00:00"}
    for f in fixtures:
        a = T.analyze_trade(f, signal_context=ctx)
        for s in a["observations"] + a["risk_flags"] + a["context"]:
            assert directive_guard(s), f"directive language leaked: {s!r}"
        assert directive_guard(T.render_prose(a, f))


# ------------------------------------------------------------------ performance analytics

def _closed(rets, strat="breakout"):
    return [{"realized_pnl_pct": r, "strategy": strat, "rr": 2.0} for r in rets]


def test_performance_insufficient_sample_is_honest():
    s = T.summarize_performance(_closed([0.1, -0.05, 0.2]))
    assert s["sufficient"] is False and s["n_closed"] == 3
    assert s["win_rate"] is None and s["expectancy"] is None
    assert "starts reporting win rate" in s["note"]


def test_performance_sufficient_sample_reports_rate_and_expectancy():
    rets = [0.1, 0.2, -0.05, 0.15, -0.1, 0.05, 0.3, -0.02, 0.08, 0.12, -0.04, 0.06]
    s = T.summarize_performance(rets and _closed(rets))
    assert s["sufficient"] is True and s["n_closed"] == 12
    assert s["wins"] == 8 and s["losses"] == 4
    assert s["win_rate"] == round(8 / 12, 4)
    assert s["avg_reward_risk"] == 2.0


def test_performance_names_an_edge_only_across_two_sufficient_strategies():
    winners = _closed([0.1] * 7 + [-0.05], "breakout")          # 7/8 wins
    losers = _closed([-0.1] * 6 + [0.05, 0.05], "reversal")     # 2/8 wins
    s = T.summarize_performance(winners + losers)
    assert s["sufficient"] is True
    assert {row["strategy"] for row in s["by_strategy"]} == {"breakout", "reversal"}
    assert len(s["insights"]) == 1
    assert "higher on breakout" in s["insights"][0]
    assert directive_guard(s["insights"][0])


def test_performance_no_edge_named_when_a_strategy_is_below_floor():
    mixed = _closed([0.1] * 10, "breakout") + _closed([-0.1] * 3, "scalp")   # scalp below floor
    s = T.summarize_performance(mixed)
    assert [row["strategy"] for row in s["by_strategy"]] == ["breakout"]      # scalp not reported
    assert s["insights"] == []                                               # no contrast to draw
