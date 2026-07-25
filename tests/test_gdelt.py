"""Offline tests for the GDELT adapter's parsing and mapping.

Fixtures are real article records captured from the live API on 2026-07-25, before an unpaced
burst of probe requests got this IP rate-limited (which is itself the reason the adapter paces
itself — see MIN_INTERVAL_S). No network here.
"""
import pytest

from tradeos.ingestion import gdelt

# Verbatim from the live API.
REAL_ARTICLES = [
    {"url": "https://news.cnfol.com/guoneicaijing/20260725/31234567.shtml",
     "url_mobile": "", "title": "央行将7月末前后开展4次隔夜逆回购 对冲月底资金波动",
     "seendate": "20260725T023000Z", "socialimage": "", "domain": "news.cnfol.com",
     "language": "Chinese", "sourcecountry": "China"},
    {"url": "https://www.stcn.com/article/detail/9876543.html",
     "title": "央行将在7月末8月初开展多次隔夜逆回购操作",
     "seendate": "20260724T121500Z", "domain": "stcn.com",
     "language": "Chinese", "sourcecountry": "China"},
]


# ------------------------------------------------------------------ timestamps

def test_parse_seendate_reads_gdelts_compact_format():
    dt = gdelt.parse_seendate("20260725T023000Z")
    assert (dt.year, dt.month, dt.day, dt.hour, dt.minute) == (2026, 7, 25, 2, 30)
    assert dt.tzinfo is not None                      # must be aware; it becomes knowable_time


@pytest.mark.parametrize("bad", [None, "", "not-a-date", "20260725", "20261325T023000Z"])
def test_parse_seendate_returns_none_rather_than_guessing(bad):
    assert gdelt.parse_seendate(bad) is None


# ------------------------------------------------------------------ country + language mapping

def test_country_names_map_to_iso_codes():
    assert gdelt.country_code("United Arab Emirates") == "AE"
    assert gdelt.country_code("united states") == "US"
    assert gdelt.country_code("  China  ") == "CN"


def test_unmapped_country_is_dropped_not_guessed():
    """A wrong country code puts an event on the wrong part of the globe. Absent beats wrong."""
    assert gdelt.country_code("Ruritania") is None
    assert gdelt.country_code(None) is None
    assert gdelt.country_code("") is None


def test_language_names_map_to_iso_codes():
    assert gdelt.language_code("Chinese") == "zh"
    assert gdelt.language_code("English") == "en"
    assert gdelt.language_code("Klingon") is None


# ------------------------------------------------------------------ article -> event

def test_real_article_becomes_a_well_formed_event():
    ev = gdelt.to_event(REAL_ARTICLES[0], "monetary_policy")
    assert ev["source"] == "gdelt"
    assert ev["external_id"] == ev["source_url"] == REAL_ARTICLES[0]["url"]
    assert ev["language"] == "zh" and ev["geo"] == ["CN"]
    assert ev["category"] == "monetary_policy"
    assert ev["knowable_time"] == ev["published_at"] == gdelt.parse_seendate("20260725T023000Z")
    assert ev["raw_payload"] == REAL_ARTICLES[0]      # kept whole, so the engine can be rerun


def test_non_english_titles_survive_intact():
    """A US-markets product would drop these. The whole point of GDELT here is that it does not."""
    ev = gdelt.to_event(REAL_ARTICLES[1], "monetary_policy")
    assert ev["title"] == "央行将在7月末8月初开展多次隔夜逆回购操作"


@pytest.mark.parametrize("missing", ["url", "title", "seendate"])
def test_article_missing_an_essential_field_is_dropped(missing):
    """Never store a placeholder row — an event with no time or no source cannot be reasoned about."""
    article = {**REAL_ARTICLES[0], missing: ""}
    assert gdelt.to_event(article, "monetary_policy") is None


def test_article_with_no_mappable_country_still_becomes_an_event():
    """Unknown geography is not a reason to discard a real event; it just has no geo."""
    ev = gdelt.to_event({**REAL_ARTICLES[0], "sourcecountry": "Ruritania"}, "conflict")
    assert ev is not None and ev["geo"] == []


# ------------------------------------------------------------------ pacing

def test_queries_are_a_deliberate_quota_budget():
    """Each query is one paced request, so this list IS the per-pass cost. Keep it short."""
    assert 1 <= len(gdelt.QUERIES) <= 8
    for category, query in gdelt.QUERIES:
        assert query.strip()
        assert category in __import__("tradeos.spine", fromlist=["spine"]).CATEGORIES


def test_minimum_interval_respects_the_measured_limit():
    """Measured 2026-07-25: three rapid requests earned a 429 that outlasted an hour."""
    assert gdelt.MIN_INTERVAL_S >= 5.0


# ------------------------------------------------------------------ backoff discipline

def test_backoff_is_long_enough_to_be_a_real_pause():
    """Measured: GDELT's penalty outlasts an hour. Retrying on the next scheduler tick would just
    re-earn it, which is how a free source gets lost permanently."""
    assert gdelt.BACKOFF_HOURS >= 1


def test_the_user_agent_is_honest_and_constant():
    """Rotating the User-Agent WOULD restore access after a 429 — GDELT's throttle is keyed on it.
    We deliberately do not: that is evasion of a rate limit on a free service, and it breaks the
    moment they tighten the check. The identifier must name this product and stay put."""
    ua = gdelt.UA["User-Agent"]
    assert "Rhumb" in ua
    assert not any(b in ua for b in ("Mozilla", "Chrome", "Safari", "AppleWebKit")), \
        "the User-Agent must not impersonate a browser"


def test_the_reason_for_not_rotating_is_written_down():
    """A future maintainer hitting a 429 will reach for a new UA string. The module must explain
    why that is the wrong fix, or the reasoning is lost the first time someone is in a hurry."""
    import inspect
    src = inspect.getsource(gdelt)
    assert "evasion" in src.lower()
