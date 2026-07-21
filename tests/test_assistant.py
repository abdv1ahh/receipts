"""Offline tests for the AI assistant's pure layer: intent classification, candidate-ticker
extraction (cashtags + all-caps, stop-list filtered), grounded answer composition from a retrieved
context, and the two invariants — every assembled answer clears the directive guard (no advice),
and its numbers all trace to the context (so the model is allowed to restate them). No DB, no network."""
from tradeos import assistant as A
from tradeos.explain.guards import allowed_numbers, directive_guard, numbers_guard


def test_classify_intents():
    assert A.classify("why is NVDA moving today")["why_moving"]
    assert A.classify("explain the breakout strategy")["concept"]
    assert A.classify("how are my trades doing")["performance"]
    assert A.classify("what are traders discussing on reddit")["sentiment"]
    assert not A.classify("show me NVDA")["sentiment"]


def test_candidate_symbols_cashtags_and_caps_minus_stoplist():
    assert A.candidate_symbols("why is NVDA moving vs $tsla and AI hype") == ["NVDA", "TSLA"]
    assert A.candidate_symbols("explain breakout trading") == []          # no uppercase tokens
    assert A.candidate_symbols("is the ETF for AI worth it") == []        # ETF, AI, and lone caps in stop-list


def _guarded(ans):
    return directive_guard(ans)


def test_answer_symbol_with_cluster():
    ctx = {"symbols": [{"symbol": "NVDA", "name": "NVIDIA",
                        "cluster": {"bucket": "high", "voices": 4, "score": 2.31,
                                    "source_classes": ["insider", "activist"]}}]}
    ans, src = A.build_answer("what's the signal on NVDA", ctx)
    assert "high-confidence smart-money convergence" in ans and "4 independent filers" in ans and "2.31" in ans
    assert src == ["signal:NVDA"]
    assert _guarded(ans)


def test_answer_symbol_without_cluster_and_unrecognized():
    ans, src = A.build_answer("NVDA?", {"symbols": [{"symbol": "NVDA", "name": "NVIDIA", "cluster": None}]})
    assert "no active convergence cluster" in ans and src == ["activity:NVDA"]
    ans2, _ = A.build_answer("what about $zzzz", {"unrecognized": ["ZZZZ"]})
    assert "isn't in the smart-money dataset" in ans2
    assert _guarded(ans) and _guarded(ans2)


def test_answer_sentiment_gap_is_honest_never_fabricated():
    ans, src = A.build_answer("what are people saying about tech on reddit", {"sentiment": True})
    assert "isn't connected yet" in ans and "gap:sentiment" in src
    assert _guarded(ans)


def test_answer_performance_sufficient_and_insufficient():
    good = A.build_answer("how am I doing", {"performance": {"sufficient": True, "win_rate": 0.6,
                                                             "avg_reward_risk": 2.0, "n_closed": 12}})[0]
    assert "win rate is 60%" in good and "2.0 to 1" in good
    low = A.build_answer("my stats", {"performance": {"sufficient": False, "n_closed": 3}})[0]
    assert "3 closed trade(s)" in low and "at least 10" in low
    assert _guarded(good) and _guarded(low)


def test_answer_empty_context_falls_back_to_top_signals_then_scope():
    top = A.build_answer("what's hot", {"top_signals": [{"symbol": "ABC", "bucket": "high"},
                                                        {"symbol": "XYZ", "bucket": "medium"}]})[0]
    assert "ABC (high)" in top and "XYZ (medium)" in top
    scope = A.build_answer("hi", {})[0]
    assert "aren't connected yet" in scope
    assert _guarded(top) and _guarded(scope)


def test_answer_numbers_all_trace_to_context():
    """The numbers guard (applied to the MODEL's answer) must accept every number the deterministic
    answer uses — proving the context + structural constants are a sufficient allow-set."""
    ctx = {"symbols": [{"symbol": "NVDA", "name": "NVIDIA",
                        "cluster": {"bucket": "high", "voices": 4, "score": 2.31, "source_classes": ["insider"]}}],
           "performance": {"sufficient": True, "win_rate": 0.6, "avg_reward_risk": 2.0, "n_closed": 12}}
    ans, _ = A.build_answer("NVDA and my performance", ctx)
    allowed = allowed_numbers(ctx, {"_const": [1, 5, 10, 100]})
    assert numbers_guard(ans, allowed)


def test_every_build_answer_output_clears_the_directive_guard():
    cases = [
        {"symbols": [{"symbol": "NVDA", "name": "NVIDIA", "cluster": {"bucket": "high", "voices": 4, "score": 2.3, "source_classes": ["insider", "activist"]}}], "why_moving": True},
        {"library": [{"slug": "breakout", "title": "The breakout"}]},
        {"performance": {"sufficient": True, "win_rate": 0.55, "avg_reward_risk": 1.8, "n_closed": 20}},
        {"sentiment": True, "unrecognized": ["MEME"]},
        {},
    ]
    for c in cases:
        ans, _ = A.build_answer("q", c)
        assert directive_guard(ans), f"directive language leaked: {ans!r}"
