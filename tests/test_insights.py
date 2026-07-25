"""Offline tests for the advanced-AI layer's pure logic (Slice L): trade similarity + cohort honesty,
the deterministic scenario simulator's arithmetic, habit aggregation, and the deterministic journal
report (which must clear both model guards by construction — it's the always-available fallback).
No network, no database."""
from tradeos import insights as I
from tradeos.explain.guards import allowed_numbers, directive_guard, numbers_guard

# ---------------- similarity + finder ----------------

def _t(id, ac="equity", d="long", strat="breakout", rr=2.0, tf="swing", pnl=None, status="closed"):
    return {"id": id, "asset_class": ac, "direction": d, "strategy": strat, "reward_risk": rr,
            "timeframe": tf, "realized_pnl_pct": pnl, "status": status, "symbol": "X", "rr": rr}


def test_similarity_scale_and_symmetry():
    a = _t(1)
    assert I.similarity(a, _t(2)) == 1.0                       # identical setup fields -> 1.0
    assert I.similarity(a, _t(2)) == I.similarity(_t(2), a)     # symmetric
    low = I.similarity(a, _t(3, ac="crypto", d="short", strat="mean reversion", rr=0.5, tf="scalp"))
    assert low < I.SIMILAR_MIN_SCORE                           # nothing in common -> below the floor


def test_find_similar_excludes_self_filters_and_ranks():
    target = _t(1)
    cands = [_t(1), _t(2), _t(3, strat="breakout pullback"),
             _t(4, ac="crypto", d="short", strat="scalp news", rr=0.4, tf="scalp")]
    out = I.find_similar(target, cands)
    ids = [c["id"] for c in out]
    assert 1 not in ids                                       # never itself
    assert 4 not in ids                                       # below min_score, dropped
    assert ids[0] == 2 and out[0]["similarity"] >= out[-1]["similarity"]  # ranked desc


def test_cohort_summary_is_honest_about_small_samples():
    assert I.summarize_cohort([])["line"].startswith("No comparable")
    few = I.summarize_cohort([_t(2, pnl=0.1), _t(3, pnl=-0.05)])
    assert few["summary"]["win_rate"] is None and "too few" in few["line"]     # no rate below floor
    many = I.summarize_cohort([_t(10 + i, pnl=(0.1 if i % 2 else -0.05)) for i in range(12)])
    assert many["summary"]["sufficient"] and many["summary"]["win_rate"] is not None


# ---------------- scenario simulator ----------------

def test_simulate_requires_entry():
    assert I.simulate({"entry_price": None})["ok"] is False


def test_simulate_long_math_and_account_risk():
    sim = I.simulate({"entry_price": 100, "stop_price": 90, "target_price": 130, "direction": "long",
                      "size": 10, "size_unit": "shares"}, account_size=10000)
    assert sim["ok"] and sim["reward_risk"] == 3.0
    assert sim["distance_to_stop_pct"] == 10.0 and sim["distance_to_target_pct"] == 30.0
    assert sim["account_risk_pct"] == 1.0                      # 10*10 / 10000
    tgt = next(r for r in sim["scenarios"] if r["label"] == "target hit")
    stp = next(r for r in sim["scenarios"] if r["label"] == "stop hit")
    assert tgt["r_multiple"] == 3.0 and tgt["return_pct"] == 30.0 and tgt["pnl_amount"] == 300.0
    assert stp["r_multiple"] == -1.0 and stp["pnl_amount"] == -100.0
    assert sim["notes"] == []                                 # stop present, risk <=2% -> no warnings


def test_simulate_flags_no_stop_and_oversized_risk():
    no_stop = I.simulate({"entry_price": 100, "target_price": 130, "direction": "long"})
    assert any("No stop" in n for n in no_stop["notes"])
    assert all(r["r_multiple"] is None for r in no_stop["scenarios"])   # can't frame R without a stop
    big = I.simulate({"entry_price": 100, "stop_price": 90, "target_price": 130, "direction": "long",
                      "size": 30, "size_unit": "shares"}, account_size=10000)
    assert big["account_risk_pct"] == 3.0 and any("% of the account" in n for n in big["notes"])


def test_simulate_short_direction():
    sim = I.simulate({"entry_price": 100, "stop_price": 110, "target_price": 70, "direction": "short"})
    assert sim["reward_risk"] == 3.0
    tgt = next(r for r in sim["scenarios"] if r["label"] == "target hit")
    assert tgt["return_pct"] == 30.0 and tgt["r_multiple"] == 3.0     # short gains as price falls


# ---------------- habits + report ----------------

def test_aggregate_habits_counts_recurring_patterns():
    analyses = [
        {"risk_flags": ["No stop level was recorded, so the downside on this idea is undefined."],
         "observations": [], "reward_risk": None},
        {"risk_flags": [], "observations": [], "reward_risk": 0.5},        # rr below 1
        {"risk_flags": [], "observations": ["Logged at high conviction (5 of 5); the recorded result was a loss — a data point for review, not a verdict."], "reward_risk": 2.0},
    ]
    habits = {h["key"]: h["count"] for h in I.aggregate_habits(analyses)}
    assert habits.get("no_stop") == 1 and habits.get("rr_below_1") == 1 and habits.get("high_conv_loss") == 1


def test_deterministic_report_is_guard_clean_and_honest():
    # below the floor: report must NOT state a win rate, and must clear both model guards by construction
    perf = {"n_closed": 4, "sufficient": False, "win_rate": None, "expectancy": None,
            "avg_reward_risk": 1.8, "by_strategy": [], "insights": []}
    report = I.build_report(perf, [{"key": "no_stop", "label": "trades logged with no stop level", "count": 2, "of": 6}], 6)
    prose = I.render_report(report)
    assert directive_guard(prose)                                   # no advice language
    assert numbers_guard(prose, allowed_numbers(report, {"_const": [1, 2, 5, 100]}))  # no invented numbers
    assert "win rate" in prose and "%" not in prose.split("floor")[0]  # names the floor, states no rate
