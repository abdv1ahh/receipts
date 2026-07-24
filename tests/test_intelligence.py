"""Offline tests for the Intelligence plane's honesty guarantees: the new citation guard (no foreign
tickers), deterministic confidence, and that every deterministic 'why it matters' / executive-summary
opener is guard-clean by construction (no advice, no fabricated numbers). No network, no database."""
from tradeos.explain.guards import allowed_numbers, directive_guard, numbers_guard
from tradeos.intelligence import analyst


# ------------------------------------------------------------------ citation guard (new to this plane)

def test_citation_guard_blocks_foreign_tickers():
    assert analyst.citation_guard("PEGA reset expectations for its peers", ["PEGA"]) is True
    assert analyst.citation_guard("this echoes $NVDA last quarter", ["PEGA"]) is False   # foreign cashtag
    assert analyst.citation_guard("compare with (NYSE: XOM)", ["PEGA"]) is False          # foreign exchange ref
    assert analyst.citation_guard("mentions $PEGA only", ["PEGA"]) is True               # in-set is fine


# ------------------------------------------------------------------ deterministic confidence

def test_confidence_is_deterministic():
    assert analyst._confidence({"source": "sec/8-k", "category": "earnings", "has_signal": False}) == "high"
    assert analyst._confidence({"source": "sec/8-k", "category": "disclosure", "has_signal": False}) == "medium"
    assert analyst._confidence({"source": "rss/cnbc", "category": "markets", "has_signal": False}) == "low"
    assert analyst._confidence({"source": "rss/cnbc", "category": "markets", "has_signal": True}) == "medium"


# ------------------------------------------------------------------ deterministic prose is guard-clean

def test_template_why_is_guard_clean_and_specific():
    it = {"symbols": ["PEGA"], "category": "earnings", "has_signal": True, "source": "sec/8-k"}
    why = analyst._template_why(it)
    assert directive_guard(why) is True                       # never advice
    assert numbers_guard(why, allowed_numbers({})) is True    # introduces no number
    assert "PEGA" in why and "smart money" in why.lower()
    assert "not advice" in why.lower()


def test_template_why_macro_has_no_symbol_subject():
    it = {"symbols": [], "category": "macro", "has_signal": False, "source": "rss/fed"}
    why = analyst._template_why(it)
    assert directive_guard(why) and "not advice" in why.lower()
    assert "macro" in why.lower()


# ------------------------------------------------------------------ executive summary (template path)

def test_executive_summary_template_leads_with_tickers_and_is_clean():
    items = [{"symbols": ["PEGA"], "category": "earnings", "headline": "PEGA results", "why_it_matters": "x"},
             {"symbols": ["TSLA"], "category": "earnings", "headline": "TSLA misses", "why_it_matters": "y"},
             {"symbols": [], "category": "macro", "headline": "Fed", "why_it_matters": "z"}]
    es = analyst.executive_summary(items, {"symbol": "ENR", "score": 100}, provider="template")
    assert es["used_template"] is True and es["model_id"] == "template"
    text = es["text"]
    assert directive_guard(text) and "not advice" in text.lower()
    assert "PEGA" in text and "TSLA" in text and "ENR" in text        # grounded in the items + signal lead


def test_executive_summary_empty_items():
    es = analyst.executive_summary([], None, provider="template")
    assert es["used_template"] and directive_guard(es["text"])


# ------------------------------------------------------------------ the guards actually bite

def test_guards_reject_advice_and_invented_numbers():
    assert directive_guard("you should buy PEGA now") is False        # advice -> rejected
    ctx = {"impact_0_100": 72, "symbols": ["PEGA"]}
    allowed = allowed_numbers(ctx)
    assert numbers_guard("impact reads 72 here", allowed) is True     # traces to context
    assert numbers_guard("the stock jumped 45% today", allowed) is False  # 45 fabricated -> rejected
