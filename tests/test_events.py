"""Offline tests for Event & Macro Intelligence pure logic: the Nasdaq row classification (US
market-movers kept, noise dropped — never fabricated), earnings importance/timing, the deterministic
macro knowledge base, and the CROSS-PLANE enrichment that flags earnings on names smart money or the
crowd is already watching. No network, no database."""
from tradeos import events
from tradeos.ingestion import calendar_nasdaq as C


# ------------------------------------------------------------------ Nasdaq classification (pure)

def test_classify_macro_us_movers_only():
    assert C.classify_macro("United States", "Consumer Price Index (CPI) YoY") == ("cpi", "high")
    assert C.classify_macro("United States", "Non-Farm Payrolls") == ("jobs", "high")
    assert C.classify_macro("United States", "FOMC Interest Rate Decision") == ("fomc", "high")
    assert C.classify_macro("United States", "ISM Manufacturing PMI") == ("macro", "medium")
    assert C.classify_macro("United States", "Redbook Retail Index") is None      # US but low-signal -> dropped
    assert C.classify_macro("Germany", "German Car Registration") is None          # non-US -> dropped


def test_parse_earnings_time_and_cap_importance():
    assert C.parse_earnings_time("time-pre-market") == "pre-market"
    assert C.parse_earnings_time("time-after-hours") == "after-hours"
    assert C.parse_earnings_time("time-not-supplied") is None
    assert C.cap_importance("$239,353,292,940") == "high"     # mega-cap
    assert C.cap_importance("$8,000,000,000") == "medium"
    assert C.cap_importance("$500,000,000") == "low"
    assert C.cap_importance(None) == "medium"                 # unknown -> neutral


# ------------------------------------------------------------------ event enrichment (pure)

def test_enrich_macro_gets_knowledge_base():
    ev = {"scope": "macro", "kind": "fomc", "symbol": None}
    out = events._enrich(ev, set(), {})
    assert "interest-rate" in out["what"].lower()
    assert "banks" in out["moves"].lower()                    # names the sectors it moves


def test_enrich_earnings_cross_plane_flags():
    sig = {"NVDA"}
    attn = {"TSLA": {"velocity": 2.1}, "KO": {"velocity": 1.0}}
    nvda = events._enrich({"scope": "company", "kind": "earnings", "symbol": "NVDA"}, sig, attn)
    assert nvda["cross_plane"] == ["smart_money"]             # signal overlap flagged
    tsla = events._enrich({"scope": "company", "kind": "earnings", "symbol": "TSLA"}, sig, attn)
    assert tsla["cross_plane"] == ["attention"] and tsla["attention_velocity"] == 2.1
    ko = events._enrich({"scope": "company", "kind": "earnings", "symbol": "KO"}, sig, attn)
    assert ko["cross_plane"] == []                            # attention below the spike threshold -> no flag


def test_notability_ranks_cross_plane_above_plain():
    plain_high = {"importance": "high", "cross_plane": []}
    earnings_attention = {"importance": "medium", "cross_plane": ["attention", "smart_money"]}
    assert events._notability(earnings_attention) > events._notability(plain_high)
