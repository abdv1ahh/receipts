"""Offline tests for the sentiment/trend scanner's pure scoring: velocity-based attention (with an
honest provisional score when there's no baseline), mention-weighted sentiment (None when unmeasured),
manipulation flags (single-source, bot-heavy), and the trending ranker's mention floor + ordering.
No network, no database."""
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
