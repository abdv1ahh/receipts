"""Offline tests for AI chart analysis: the advice guard applied field by field to a model's chart
read, the honest fallback that names the REAL reason there is no AI read, and the regression that
started this — a correct chart read being discarded because it said "target price". No network.

The model transport is mocked; a real PNG fixture (tests/fixtures/chart_nvda.png) is fed through the
same path a user's screenshot takes, so the bytes-to-request plumbing is exercised for real."""
import json
import pathlib

from tradeos import llm
from tradeos.explain.guards import directive_guard
from tradeos.intelligence import vision

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "chart_nvda.png"

TRADE = {"symbol": "NVDA", "direction": "long", "status": "open",
         "entry_price": 120, "stop_price": 110, "target_price": 145, "strategy": "breakout"}

# The exact reply gpt-4o-mini produced for this user's real screenshot on 2026-07-25, which the
# old all-or-nothing guard threw away in full.
REAL_REPLY = {
    "pattern": "breakout",
    "structure": "The price is in a strong upward trend. Notable support is identified at the stop "
                 "level, while the entry level sits below the current price action.",
    "risk_reward": "The risk is defined by the distance between the entry price and the stop price, "
                   "while the reward is the distance from the entry price to the target price.",
    "observations": ["Consider documenting the rationale behind the levels in your journal.",
                     "Evaluate position sizing against your risk management plan."],
    "psychology": "Staying disciplined helps mitigate emotional responses during trades.",
    "is_chart": True, "symbol": "NVDA", "timeframe": "1h", "direction": "long",
    "entry": 120.0, "stop": 110.0, "target": 145.0,
}


def _mock_model(monkeypatch, reply, reason=""):
    """Stub the transport, capturing what the caller sent it."""
    cap: dict = {}

    def fake(prompt, image=None, max_tokens=400, json_mode=False, provider=None, role=llm.DEEP):
        cap.update({"prompt": prompt, "image": image, "json_mode": json_mode, "provider": provider})
        return (json.dumps(reply) if isinstance(reply, dict) else reply), reason

    monkeypatch.setattr(vision.llm, "complete", fake)
    return cap


# ------------------------------------------------------------------ the regression (bug B-01)

def test_descriptive_risk_reward_prose_is_not_treated_as_advice():
    """'the distance from the entry price to the target price' describes the user's own recorded
    levels. Banning it discarded correct chart reads and made the app claim no model was connected."""
    assert directive_guard(REAL_REPLY["risk_reward"]) is True


def test_analyst_style_price_targets_are_still_refused():
    assert directive_guard("price target of $190 by year end") is False
    assert directive_guard("raised its price target to $200") is False
    assert directive_guard("we set a target price of 145") is False
    assert directive_guard("strong buy, outperform") is False


def test_the_real_reply_now_survives_end_to_end(monkeypatch):
    cap = _mock_model(monkeypatch, REAL_REPLY)
    out = vision.analyze_chart(FIXTURE.read_bytes(), "image/png", trade=TRADE, provider="gemini")
    assert out["ok"] is True and out["source"] == "ai" and out["used_template"] is False
    assert out["pattern"] == "breakout"
    assert "distance from the entry price" in out["risk_reward"]
    assert len(out["observations"]) == 2
    assert out["withheld"] == []
    assert out["detected"]["symbol"] == "NVDA" and out["detected"]["entry"] == 120.0
    # the image really was attached, as bytes, with its true mime type
    assert cap["image"][0] == FIXTURE.read_bytes() and cap["image"][1] == "image/png"
    assert cap["json_mode"] is True


# ------------------------------------------------------------------ guard: withhold the field, keep the read

def test_guard_drops_only_the_offending_field():
    bad = {**REAL_REPLY, "psychology": "you should buy the breakout"}
    clean, dropped = vision._guard_fields(bad)
    assert dropped == ["psychology"]
    assert clean["psychology"] is None
    assert clean["pattern"] == "breakout" and clean["structure"] == REAL_REPLY["structure"]


def test_guard_filters_a_single_bad_observation():
    bad = {**REAL_REPLY, "observations": ["risk sits below the trendline", "you should sell now"]}
    clean, dropped = vision._guard_fields(bad)
    assert dropped == ["observations"] and clean["observations"] == ["risk sits below the trendline"]


def test_a_read_that_is_entirely_advice_falls_back(monkeypatch):
    allbad = {"pattern": "you should buy", "structure": "we recommend buying shares",
              "risk_reward": "raise your price target to 200", "psychology": "you must sell now",
              "observations": ["you should add on the dip"], "is_chart": True}
    _mock_model(monkeypatch, allbad)
    out = vision.analyze_chart(FIXTURE.read_bytes(), "image/png", trade=TRADE, provider="gemini")
    assert out["used_template"] is True
    assert "withheld by the advice guard" in out["reason"]           # the real reason, not a guess


# ------------------------------------------------------------------ fallback: says what actually happened

def test_fallback_reports_a_quota_trip_as_a_quota_trip(monkeypatch):
    _mock_model(monkeypatch, None, reason="gemini hit its quota")
    out = vision.analyze_chart(FIXTURE.read_bytes(), "image/png", trade=TRADE, provider="gemini")
    assert out["used_template"] is True and out["source"] == "levels"
    assert "gemini hit its quota" in out["structure"]
    assert "no vision model connected" not in out["structure"].lower()
    assert "2.5" in (out["risk_reward"] or "")                        # (145-120)/(120-110) from levels


def test_fallback_reports_unparseable_json_honestly(monkeypatch):
    _mock_model(monkeypatch, "I'm sorry, I can't help with that.")
    out = vision.analyze_chart(FIXTURE.read_bytes(), "image/png", trade=TRADE, provider="gemini")
    assert out["used_template"] is True and "not valid JSON" in out["reason"]


def test_fallback_uses_recorded_levels_for_a_trade():
    out = vision._fallback(TRADE, "gemini has no API key set")
    assert out["ok"] is True and out["used_template"] is True and out["source"] == "levels"
    assert "no API key" in out["structure"]
    assert "2.5" in (out["risk_reward"] or "")


def test_fallback_without_a_trade_is_honest():
    out = vision._fallback(None, "no model provider is configured")
    assert out["ok"] is False and out["source"] == "none"
    assert "no model provider is configured" in out["structure"]


def test_analyze_chart_template_provider_never_calls_a_model():
    out = vision.analyze_chart(FIXTURE.read_bytes(), "image/png",
                               trade={"entry_price": 50, "stop_price": 45, "target_price": 65,
                                      "direction": "long", "status": "open"}, provider="template")
    assert out["used_template"] is True and out["source"] == "levels"
    assert "3" in (out["risk_reward"] or "")                         # 15/5 = 3.0 reward:risk
    assert out["detected"] == {}                                     # fallback pre-fills nothing
    assert "switched off" in out["reason"]


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
