"""Offline tests for the Dashboard's Market Pulse — the one place the redesign computes a *number* from
many inputs, so the honesty bar is highest here. No network, no database: the two DB probes
(_insider_flow, _convergence_breadth) are monkeypatched with synthetic facts and the pure scoring,
driver-generation, risk tiering, and deterministic headline are asserted directly.

The invariants under test are exactly the product's promises: the score is neutral (50) with no data;
every point of movement is explained by a driver; the headline gives no advice; and an empty tape
degrades to an honest reading rather than a fabricated one."""
from datetime import date, timedelta

from tradeos import dashboard


# ------------------------------------------------------------------ helpers

def _flow(ratio, total, buys=None, sells=None):
    buys = buys if buys is not None else int(round((ratio or 0) * total))
    sells = sells if sells is not None else total - buys
    return {"buys": buys, "sells": sells, "buy_usd": 0.0, "sell_usd": 0.0,
            "total": total, "ratio": ratio}


def _conv(high=0, medium=0, low=0):
    return {"high": high, "medium": medium, "low": low, "total": high + medium + low}


def _patch(monkeypatch, flow, conv):
    monkeypatch.setattr(dashboard, "_insider_flow", lambda conn, as_of: flow)
    monkeypatch.setattr(dashboard, "_convergence_breadth", lambda conn, as_of: conv)


def _news(impact, n=1):
    return [{"id": i, "impact": impact, "headline": f"item {i}"} for i in range(n)]


# ------------------------------------------------------------------ pure helpers

def test_nearest_high_macro_picks_soonest_high_only():
    today = date.today()
    radar = [
        {"scope": "macro", "importance": "medium", "date": (today + timedelta(1)).isoformat(), "title": "PPI"},
        {"scope": "macro", "importance": "high", "date": (today + timedelta(4)).isoformat(), "title": "CPI"},
        {"scope": "macro", "importance": "high", "date": (today + timedelta(2)).isoformat(), "title": "FOMC"},
        {"scope": "company", "importance": "high", "date": today.isoformat(), "title": "NVDA earnings"},
    ]
    days, title = dashboard._nearest_high_macro(radar)
    assert (days, title) == (2, "FOMC")          # soonest HIGH-importance MACRO, not the earnings/medium


def test_nearest_high_macro_none_when_absent():
    assert dashboard._nearest_high_macro([]) == (None, None)
    assert dashboard._nearest_high_macro(
        [{"scope": "company", "importance": "high", "date": date.today().isoformat(), "title": "x"}]
    ) == (None, None)


def test_headline_gives_no_advice_and_cites_lead():
    txt = dashboard._headline("risk_on", {"symbol": "NVDA"}, "CPI", 1)
    assert txt.endswith("Context, not advice.")
    assert "NVDA" in txt and "CPI" in txt
    banned = ("buy", "sell", "should", "recommend", "target", "hold ")
    assert not any(w in txt.lower() for w in banned)


# ------------------------------------------------------------------ market pulse: honest scoring

def test_pulse_neutral_and_honest_with_no_data(monkeypatch):
    _patch(monkeypatch, _flow(None, 0, buys=0, sells=0), _conv())
    p = dashboard._market_pulse(None, None, {"lead": None}, [], [], [])
    assert p["score"] == 50                       # neutral, not invented
    assert p["tone"] == "mixed" and p["risk"] == "low"
    assert p["drivers"] == [] and p["have_data"] is False
    assert p["measures"] == "flow & positioning"  # labels WHAT it measures — no fake "sentiment"
    assert p["headline"].endswith("Context, not advice.")


def test_pulse_risk_on_when_insiders_accumulate(monkeypatch):
    _patch(monkeypatch, _flow(0.8, 20), _conv(high=2, medium=1))
    p = dashboard._market_pulse(None, None, {"lead": {"symbol": "NVDA"}}, [], [], [])
    assert p["tone"] == "risk_on" and p["score"] >= 60
    labels = {d["label"] for d in p["drivers"]}
    assert {"Insider flow", "Convergence"} <= labels
    flow_driver = next(d for d in p["drivers"] if d["label"] == "Insider flow")
    assert flow_driver["pol"] == "pos" and "net buyers" in flow_driver["text"]


def test_pulse_risk_off_and_elevated_when_distribution(monkeypatch):
    _patch(monkeypatch, _flow(0.2, 20), _conv())
    p = dashboard._market_pulse(None, None, {"lead": None}, [], [], [])
    assert p["tone"] == "risk_off" and p["score"] < 42
    assert p["risk"] == "elevated"                # net selling with a real sample raises event risk
    assert next(d for d in p["drivers"] if d["label"] == "Insider flow")["pol"] == "neg"


def test_pulse_flags_high_risk_on_imminent_macro(monkeypatch):
    _patch(monkeypatch, _flow(None, 0, buys=0, sells=0), _conv())
    radar = [{"scope": "macro", "importance": "high",
              "date": (date.today() + timedelta(1)).isoformat(), "title": "FOMC"}]
    p = dashboard._market_pulse(None, None, {"lead": None}, [], radar, [])
    assert p["risk"] == "high"                     # scheduled volatility within 2 days
    macro = next(d for d in p["drivers"] if d["label"] == "Macro")
    assert macro["pol"] == "warn" and "tomorrow" in macro["text"]


def test_pulse_high_news_load_flags_risk_and_drags_score(monkeypatch):
    _patch(monkeypatch, _flow(0.5, 10), _conv())
    heavy = _news(impact=80, n=4)                  # four high-impact stories
    p = dashboard._market_pulse(None, None, {"lead": None}, heavy, [], [])
    assert p["risk"] == "high"
    assert any(d["label"] == "News load" and d["pol"] == "warn" for d in p["drivers"])


def test_pulse_score_stays_in_bounds(monkeypatch):
    _patch(monkeypatch, _flow(1.0, 50), _conv(high=9))   # maximally constructive inputs
    p = dashboard._market_pulse(None, None, {"lead": None}, [], [], [])
    assert 2 <= p["score"] <= 98
