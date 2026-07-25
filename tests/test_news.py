"""Offline tests for News Intelligence pure logic: 8-K item extraction + headline composition (a
controlled-vocabulary lookup, never a guess), RSS/Atom parsing, HIGH-PRECISION ticker tagging (no
fabricated associations), and the deterministic impact + recency ranking. No network, no database."""
from datetime import UTC, datetime, timedelta

from tradeos import news
from tradeos.ingestion import news_rss, news_sec

# ------------------------------------------------------------------ SEC 8-K item extraction + headline

def test_extract_items_known_ordered_deduped():
    body = "Item 2.02 Results of Operations ... Item 9.01 Exhibits ... Item 2.02 again ... Item 99.9 bogus"
    assert news_sec.extract_items(body) == ["2.02", "9.01"]      # known only, first-seen order, deduped


def test_compose_leads_with_salient_item_and_categorizes():
    hl, summary, cat = news_sec.compose("STEEL DYNAMICS INC", ["9.01", "2.02"])
    assert cat == "earnings"                                     # 2.02 (earnings) outranks 9.01 (exhibits)
    assert "reported results of operations" in hl.lower()
    assert "(+1 more)" in hl                                     # two items -> notes the extra
    assert summary.endswith(".")


def test_compose_officer_change_and_empty():
    _, _, cat = news_sec.compose("Aware Inc", ["5.02"])
    assert cat == "officer_change"
    hl, summary, cat0 = news_sec.compose("Tiny Co", [])
    assert cat0 == "general" and "material event" in hl.lower()  # honest fallback when no items parse


# ------------------------------------------------------------------ RSS / Atom parsing

def test_parse_feed_rss_and_atom():
    rss = b"""<?xml version='1.0'?><rss version='2.0'><channel>
      <item><title>Tesla misses on earnings</title><link>https://x.test/a</link>
            <description>free cash flow turns negative</description><guid>g1</guid>
            <pubDate>Wed, 22 Jul 2026 14:30:00 GMT</pubDate></item></channel></rss>"""
    out = news_rss.parse_feed(rss)
    assert len(out) == 1 and out[0].title == "Tesla misses on earnings"
    assert out[0].external_id == "g1" and out[0].published_at is not None

    atom = b"""<?xml version='1.0'?><feed xmlns='http://www.w3.org/2005/Atom'>
      <entry><title>Fed holds rates</title><link href='https://x.test/b'/>
             <summary>policy statement</summary><id>id2</id>
             <updated>2026-07-22T18:00:00Z</updated></entry></feed>"""
    out2 = news_rss.parse_feed(atom)
    assert out2[0].title == "Fed holds rates" and out2[0].url == "https://x.test/b"


def test_parse_feed_skips_incomplete_and_strips_html():
    # real feeds escape HTML in the body (or wrap it in CDATA); the item with no link is dropped.
    xml = b"""<rss version='2.0'><channel>
      <item><title>No link here</title></item>
      <item><title>Clean Title</title><link>https://x.test/c</link>
            <description>&lt;p&gt;body &amp; more&lt;/p&gt;</description></item></channel></rss>"""
    out = news_rss.parse_feed(xml)
    assert len(out) == 1 and out[0].title == "Clean Title"        # link-less item dropped
    assert out[0].summary == "body & more"                        # escaped HTML unescaped, then stripped


# ------------------------------------------------------------------ ticker tagging: precision first

def test_tag_symbols_precise_signals_only():
    known = {"NVDA", "TSLA", "NOW", "MU", "F"}
    idx = {"servicenow": "NOW", "nvidia": "NVDA"}
    assert news_rss.tag_symbols("$NVDA rips after hours", known) == ["NVDA"]        # cashtag
    assert news_rss.tag_symbols("results (NASDAQ: TSLA) beat", known) == ["TSLA"]   # exchange-qualified
    assert news_rss.tag_symbols("Nvidia and ServiceNow both climb", known, idx) == ["NVDA", "NOW"]


def test_tag_symbols_rejects_unknown_and_ambiguous():
    known = {"NVDA", "NOW"}
    assert news_rss.tag_symbols("$ZZZZ to the moon", known) == []          # not in our universe
    assert news_rss.tag_symbols("markets rally now that CPI cooled", known) == []  # 'now' word != $NOW ticker
    assert news_rss.tag_symbols("oil prices settle higher", known) == []   # macro, untagged (not fabricated)


# ------------------------------------------------------------------ deterministic impact + ranking

def test_intrinsic_impact_weights_signal_and_mention():
    base_earn = news.intrinsic_impact("earnings", has_signal=False)
    assert news.intrinsic_impact("earnings", has_signal=True) == base_earn + news.SIGNAL_BONUS
    assert news.intrinsic_impact("earnings", False, "mentioned") == base_earn - news.MENTION_DISCOUNT
    assert news.intrinsic_impact("distress", True) == 100            # 90 + 15 clamps to 100
    assert news.intrinsic_impact("unknown-cat", False) == 30         # default floor


def test_rank_value_decays_with_age():
    now = datetime(2026, 7, 22, tzinfo=UTC)
    fresh = news.rank_value(80, now, now)
    day_old = news.rank_value(80, now - timedelta(hours=news.RANK_HALF_LIFE_H), now)
    assert fresh == 80
    assert round(day_old, 0) == 40                                   # one half-life -> halved
    # a day-old high-impact event still outranks a fresh low-impact one
    assert day_old > news.rank_value(38, now, now)
