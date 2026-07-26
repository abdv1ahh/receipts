"""Offline tests for the sentiment/trend scanner's pure scoring: velocity-based attention (with an
honest provisional score when there's no baseline), mention-weighted sentiment (None when unmeasured),
manipulation flags (single-source, bot-heavy), and the trending ranker's mention floor + ordering.
No network, no database."""
import pytest

from tradeos import sentiment as S


def test_attention_score_velocity_and_provisional():
    assert S.attention_score(0, None) == 0
    assert S.attention_score(10, None) > 0            # provisional volume score, no history
    assert S.attention_score(10, 10) == 50            # ratio 1 -> 50
    assert S.attention_score(70, 10) == 100           # big spike, capped
    assert S.attention_score(5, 10) < 50              # below baseline


def test_blend_sentiment_weighted_and_none():
    obs = [{"mentions": 10, "sentiment": 0.8}, {"mentions": 30, "sentiment": -0.2}]
    assert S.blend_sentiment(obs) == round((10 * 0.8 + 30 * -0.2) / 40, 3)
    assert S.blend_sentiment([{"mentions": 5, "sentiment": None}]) is None   # unmeasured -> honest None
    assert S.blend_sentiment([]) is None


def test_manipulation_flags():
    single = [{"source": "hn", "mentions": 100, "bots_filtered": 0}]
    assert "single_source" in S.manipulation_flag(single)
    bots = [{"source": "reddit", "mentions": 10, "bots_filtered": 40},
            {"source": "hn", "mentions": 5, "bots_filtered": 0}]
    assert "bot_heavy" in S.manipulation_flag(bots)
    clean = [{"source": "hn", "mentions": 10, "bots_filtered": 0},
             {"source": "reddit", "mentions": 8, "bots_filtered": 1}]
    assert S.manipulation_flag(clean) == []


def test_trending_applies_mention_floor_and_orders_by_attention():
    grouped = {
        "AAA": {"name": "Alpha", "obs": [{"source": "hn", "mentions": 60, "baseline": 10, "sentiment": None, "bots_filtered": 0}]},
        "BBB": {"name": "Beta", "obs": [{"source": "hn", "mentions": 12, "baseline": 10, "sentiment": None, "bots_filtered": 0}]},
        "CCC": {"name": "Gamma", "obs": [{"source": "hn", "mentions": 1, "baseline": None, "sentiment": None, "bots_filtered": 0}]},
    }
    board = S.trending(grouped, min_mentions=3)
    syms = [x["symbol"] for x in board]
    assert "CCC" not in syms                          # below the mention floor -> excluded, not shown as noise
    assert syms[0] == "AAA"                            # higher velocity ranks first
    top = board[0]
    assert top["velocity"] == 6.0 and top["is_new"] is False and top["flags"] == ["single_source"]


def test_sources_status_is_honest():
    st = S.sources_status()
    assert st["hn"]["state"] == "connected"            # keyless, wired by default
    assert st["x"]["state"] == "unavailable"           # no free tier -> never faked
    assert st["reddit"]["state"] in ("connected", "needs_key")


# ------------------------------------------------------------------ regression: the inflated board (B-02)

def test_velocity_is_not_inflated_by_a_source_with_no_baseline():
    """The board used to divide total mentions (all sources) by total baseline (only sources that
    HAVE one), which turned a flat 1.0x name into a multi-x 'spike' and pushed noise to the top."""
    obs = [{"source": "wikipedia", "mentions": 312, "baseline": 310.0, "sentiment": None},
           {"source": "hn", "mentions": 40, "baseline": None, "sentiment": None}]
    out = S.score_symbol("BALL", "BALL Corp", obs)
    assert out["velocity"] == 1.01                       # the Wikipedia ratio, not 352/310 = 1.14
    assert out["mentions"] == 352                        # volume still counts every source
    assert out["is_new"] is False


def test_velocity_is_mention_weighted_across_sources():
    obs = [{"source": "wikipedia", "mentions": 900, "baseline": 300.0, "sentiment": None},   # 3.0x
           {"source": "reddit", "mentions": 100, "baseline": 100.0, "sentiment": 0.5}]       # 1.0x
    out = S.score_symbol("X", "X", obs)
    assert out["velocity"] == 2.8                        # (900*3 + 100*1) / 1000, not (3+1)/2


def test_no_baseline_anywhere_means_no_velocity_claimed():
    obs = [{"source": "hn", "mentions": 25, "baseline": None, "sentiment": None}]
    out = S.score_symbol("NEW", "New Co", obs)
    assert out["velocity"] is None and out["is_new"] is True


# ------------------------------------------------ share classes are one company (post-Phase 9)

def _row(sym, source, mentions, baseline, ent, name="Alphabet Inc.", sent=None):
    return (sym, source, mentions, baseline, sent, 0, name, ent)


def test_dual_class_listings_are_one_board_row():
    """Alphabet files as one issuer and trades as GOOG and GOOGL. Keyed by ticker it appeared on
    the attention board twice with its attention split — and each half then measured against its
    own baseline, so a real spike could miss the mention floor in both."""
    g = S._group([_row("GOOG", "hn", 5, 10, 3), _row("GOOGL", "hn", 7, 14, 3)])
    assert list(g) == ["GOOG"]
    assert g["GOOG"]["share_classes"] == ["GOOG", "GOOGL"]


def test_merged_mentions_and_baselines_both_add():
    """Summing counts against a half baseline would manufacture a spike."""
    g = S._group([_row("GOOG", "hn", 5, 10, 3), _row("GOOGL", "hn", 7, 14, 3)])
    hn = next(o for o in g["GOOG"]["obs"] if o["source"] == "hn")
    assert hn["mentions"] == 12 and hn["baseline"] == 24


def test_a_ticker_with_no_entity_is_never_merged_into_another():
    """An unresolved ticker has no company to belong to. Merging on name or prefix would put
    unrelated issuers together, which is worse than a duplicate row."""
    g = S._group([_row("GOOG", "hn", 5, 10, 3), _row("WEIRD", "hn", 3, 1, None, name=None)])
    assert sorted(g) == ["GOOG", "WEIRD"]


def test_the_displayed_ticker_is_deterministic():
    """"Whichever class has more mentions today" would let a board row rename itself between
    refreshes, which reads as a bug even when the number is right."""
    assert S._primary(["GOOGL", "GOOG"]) == "GOOG"
    assert S._primary(["FOXA", "FOX"]) == "FOX"
    assert S._primary(["BRK.B", "BRK.A"]) == "BRK.A"
    assert S._primary(["GOOG", "GOOGL"]) == S._primary(["GOOGL", "GOOG"])


def test_the_merge_is_disclosed_rather_than_silent():
    """A reader who searches GOOGL has to be able to see why the board says GOOG."""
    g = S._group([_row("GOOG", "hn", 5, 10, 3), _row("GOOGL", "hn", 7, 14, 3)])
    row = next(r for r in S.trending(g, min_mentions=1))
    assert row["share_classes"] == ["GOOG", "GOOGL"]


def test_a_single_class_name_carries_no_share_class_noise():
    g = S._group([_row("NVDA", "hn", 9, 4, 77, name="NVIDIA")])
    row = S.trending(g, min_mentions=1)[0]
    assert "share_classes" not in row


def test_sentiment_merges_weighted_by_mentions():
    """The class carrying more of the conversation carries more of the mood."""
    g = S._group([_row("GOOG", "reddit", 10, 5, 3, sent=1.0),
                          _row("GOOGL", "reddit", 30, 15, 3, sent=0.0)])
    o = next(x for x in g["GOOG"]["obs"] if x["source"] == "reddit")
    assert o["sentiment"] == pytest.approx(0.25)     # (1.0*10 + 0.0*30) / 40
