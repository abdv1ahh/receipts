"""Offline tests for Social & Attention Intelligence pure logic: Wikipedia pageview velocity, Reddit
ticker extraction + transparent lexicon sentiment, the attention 'why' (deterministic, guard-clean,
honest about a missing catalyst), and the honest multi-source status. No network, no database."""
from tradeos import sentiment
from tradeos.explain.guards import allowed_numbers, directive_guard, numbers_guard
from tradeos.ingestion import attention_wiki as W
from tradeos.ingestion import social_reddit as R
from tradeos.intelligence import analyst

# ------------------------------------------------------------------ Wikipedia pageview velocity

def test_velocity_from_views():
    assert W.velocity_from_views([]) == (0, None)
    assert W.velocity_from_views([100]) == (100, None)            # single day -> no baseline
    recent, base = W.velocity_from_views([100, 100, 100, 300])    # baseline = mean of prior days
    assert recent == 300 and base == 100.0                        # a 3x attention spike


# ------------------------------------------------------------------ Reddit extraction + sentiment

def test_reddit_extract_cashtag_and_bare_but_skip_common_words():
    known = {"GME", "NVDA", "TSLA", "AMC"}
    got = R.extract_symbols("YOLO $GME calls, NVDA to the moon, IT and DD are not tickers, TSLA", known)
    assert got == ["GME", "NVDA", "TSLA"]                         # IT/DD/YOLO in stoplist -> skipped
    assert R.extract_symbols("no tickers here", known) == []


def test_reddit_lexicon_sentiment():
    assert R.lexicon_sentiment("calls, bullish, moon, buy") == 1.0
    assert R.lexicon_sentiment("puts, short, crash, dump") == -1.0
    assert R.lexicon_sentiment("earnings are tomorrow") is None   # neither side -> honest None
    assert -1.0 <= R.lexicon_sentiment("calls but also puts and a crash") <= 1.0


# ------------------------------------------------------------------ attention 'why' (deterministic)

def test_attention_why_connects_to_news_catalyst():
    attn = {"attention": 80, "velocity": 2.1, "sources": ["wikipedia"], "sentiment": None}
    news = [{"headline": "Acme reported results of operations", "category": "earnings"}]
    out = analyst.attention_why("ACME", attn, news, provider="template")
    assert out["used_template"] and out["confidence"] == "high"   # real spike + catalyst
    assert "ACME" in out["text"] and "reported results" in out["text"]
    assert directive_guard(out["text"]) and "not advice" in out["text"].lower()


def test_attention_why_is_honest_when_no_catalyst():
    attn = {"attention": 60, "velocity": 1.4, "sources": ["hn"], "sentiment": None}
    out = analyst.attention_why("ZZZ", attn, [], provider="template")
    assert out["confidence"] == "low"                             # attention, no catalyst -> low
    assert "no obvious news catalyst" in out["text"].lower()      # never invents one
    assert directive_guard(out["text"]) and numbers_guard(out["text"], allowed_numbers({"v": 1.4}))


def test_attention_confidence_rules():
    news = [{"headline": "x", "category": "earnings"}]
    assert analyst._attention_confidence({"velocity": 2.0}, news) == "high"
    assert analyst._attention_confidence({"velocity": 1.1}, news) == "medium"   # catalyst but weak spike
    assert analyst._attention_confidence({"velocity": 5.0}, []) == "low"        # spike, no catalyst


# ------------------------------------------------------------------ honest source status

def test_sources_status_multi_source_honest():
    st = sentiment.sources_status()
    assert st["wikipedia"]["state"] == "connected" and st["wikipedia"]["sentiment"] is False
    assert st["stocktwits"]["state"] == "unavailable"            # datacenter-blocked -> never faked
    assert st["reddit"]["state"] in ("connected", "needs_key")
    assert st["hn"]["state"] == "connected"
