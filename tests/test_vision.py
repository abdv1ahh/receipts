"""Offline tests for AI chart analysis (Milestone 6): the advice guard on every field of a model's
chart read, and the honest deterministic fallback (level-based analysis for a logged trade, a
'connect a vision model' note otherwise). No network, no database, no image model."""
from tradeos.intelligence import vision


# ------------------------------------------------------------------ guard: no advice slips through

def test_guarded_accepts_educational_rejects_advice():
    clean = {"pattern": "ascending triangle", "structure": "higher lows into resistance",
             "risk_reward": "reward is about twice the risk from the marked levels",
             "observations": ["risk sits below the trendline", "consider what you'd journal here"],
             "psychology": "the plan looks patient"}
    assert vision._guarded(clean) is True
    # advice in ANY field must fail the whole thing
    assert vision._guarded({**clean, "observations": ["you should buy the breakout"]}) is False
    assert vision._guarded({**clean, "psychology": "recommend adding on the dip"}) is False


# ------------------------------------------------------------------ fallback: honest, never fabricated

def test_fallback_uses_recorded_levels_for_a_trade():
    trade = {"symbol": "NVDA", "direction": "long", "status": "open",
             "entry_price": 108, "stop_price": 102, "target_price": 118, "strategy": "breakout"}
    out = vision._fallback(trade)
    assert out["ok"] is True and out["used_template"] is True and out["source"] == "levels"
    assert "available" in out["structure"].lower()                    # honest about no vision model
    assert "1.67" in (out["risk_reward"] or "")                       # reward:risk 10/6 from the levels


def test_fallback_without_a_trade_is_honest():
    out = vision._fallback(None)
    assert out["ok"] is False and out["source"] == "none"
    assert "vision model" in out["structure"].lower()                # tells the user how to enable it


def test_analyze_chart_template_provider_falls_back():
    # provider 'template' never calls a model -> deterministic fallback, no network
    out = vision.analyze_chart(b"not-a-real-image", "image/png",
                               trade={"entry_price": 50, "stop_price": 45, "target_price": 65,
                                      "direction": "long", "status": "open"}, provider="template")
    assert out["used_template"] is True and out["source"] == "levels"
    assert "3" in (out["risk_reward"] or "")                         # 15/5 = 3.0 reward:risk
    assert out["detected"] == {}                                     # fallback pre-fills nothing


# ------------------------------------------------------------------ detected pre-fill: honest, never guessed

def test_detected_passes_through_visible_only():
    out = vision._detected({"symbol": "nvda", "timeframe": "1h", "direction": "long",
                            "entry": "165.5", "stop": 155, "target": None})
    assert out == {"symbol": "NVDA", "timeframe": "1h", "direction": "long",
                   "entry": 165.5, "stop": 155.0, "target": None}     # symbol upper, target stays null


def test_detected_rejects_junk_and_bad_direction():
    out = vision._detected({"symbol": "", "timeframe": "", "direction": "sideways",
                            "entry": "n/a", "stop": "", "target": "abc"})
    assert out == {"symbol": None, "timeframe": None, "direction": None,
                   "entry": None, "stop": None, "target": None}       # nothing fabricated from junk


def test_num_coerces_or_none():
    assert vision._num("165.5") == 165.5 and vision._num(10) == 10.0
    assert vision._num(None) is None and vision._num("") is None and vision._num("abc") is None
