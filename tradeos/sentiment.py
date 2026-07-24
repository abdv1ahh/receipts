"""Sentiment & trend scanner (Slice H): attention and sentiment from PUBLIC sources, scored honestly.

Every observation carries its source and timestamp; a symbol reaches the board only above a real
mention floor (no lone post is a 'trend'); attention is a velocity score vs the symbol's own recent
baseline; and manipulation resistance is explicit — a spike from a single source, or a high filtered-
bot share, is flagged, not hidden. Sources with no clean free access (X) or no configured key
(Reddit/YouTube until the operator adds one) are simply 'not connected' — never fabricated. Hacker
News (Algolia) is a free, keyless, ToS-clean source wired by default.

Pure scoring first, then the DB read/write and the honest source-status map.
"""
from __future__ import annotations

import math

import psycopg
from psycopg.types.json import Json

from . import config

DEFAULT_WINDOW_HOURS = 48
MIN_MENTIONS = 3           # below this a symbol is not a 'trend' (honest floor)


# ------------------------------------------------------------------ pure scoring

def attention_score(mentions, baseline=None) -> int:
    """0–100. With a baseline it is a velocity score (ratio of current mentions to the typical
    window); with no history it is a provisional volume score (the caller marks the row `is_new`)."""
    m = max(0, int(mentions or 0))
    if not baseline or baseline <= 0:
        return min(100, round(15 * math.log2(1 + m)))
    ratio = m / baseline
    return max(0, min(100, round(50 * math.log2(1 + ratio))))


def blend_sentiment(obs) -> float | None:
    """Mention-weighted sentiment across the sources that carry it, or None when none do (honest:
    attention can be real while sentiment is simply not measured by the connected sources)."""
    w = [(o["mentions"], o["sentiment"]) for o in obs
         if o.get("sentiment") is not None and o.get("mentions")]
    tot = sum(m for m, _ in w)
    return round(sum(m * s for m, s in w) / tot, 3) if tot else None


def manipulation_flag(obs) -> list[str]:
    """Explicit, honest manipulation-resistance labels for a symbol's attention."""
    if not obs:
        return []
    flags = []
    if len({o["source"] for o in obs}) == 1:
        flags.append("single_source")          # no independent corroboration
    bots = sum(o.get("bots_filtered", 0) for o in obs)
    total = sum(o.get("mentions", 0) for o in obs) + bots
    if total and bots / total > 0.4:
        flags.append("bot_heavy")
    return flags


def score_symbol(symbol, name, obs) -> dict:
    mentions = sum(o.get("mentions", 0) for o in obs)
    baseline = sum((o.get("baseline") or 0) for o in obs) or None
    return {"symbol": symbol, "name": name or symbol, "mentions": mentions,
            "attention": attention_score(mentions, baseline),
            "sentiment": blend_sentiment(obs),
            "velocity": round(mentions / baseline, 2) if baseline else None,
            "sources": sorted({o["source"] for o in obs}),
            "is_new": baseline is None, "flags": manipulation_flag(obs)}


def trending(grouped, min_mentions=MIN_MENTIONS, limit=25) -> list[dict]:
    """Rank symbols by attention, keeping only those above the mention floor. `grouped` is
    {symbol: {"name": .., "obs": [..]}} — the pure ranking core the DB layer feeds."""
    scored = [score_symbol(s, g.get("name"), g["obs"]) for s, g in grouped.items()]
    scored = [x for x in scored if x["mentions"] >= min_mentions]
    scored.sort(key=lambda x: (x["attention"], x["mentions"]), reverse=True)
    return scored[:limit]


# ------------------------------------------------------------------ honest source status

def sources_status() -> dict:
    """Which sources are actually connected, derived from config — never fabricated. Wikipedia + HN are
    keyless attention/discussion sources wired by default; Reddit/YouTube need the operator's free key
    (Reddit via a ToS-compliant OAuth app); StockTwits and X have no reachable free tier and stay
    unavailable rather than faked. `attention` = measures public attention; `sentiment` = measures mood."""
    return {
        "wikipedia": {"label": "Wikipedia attention", "state": "connected", "attention": True, "sentiment": False},
        "hn": {"label": "Hacker News", "state": "connected", "attention": True, "sentiment": False},
        "reddit": {"label": "Reddit", "state": "connected" if config.reddit_configured() else "needs_key", "attention": True, "sentiment": True},
        "youtube": {"label": "YouTube", "state": "connected" if config.youtube_configured() else "needs_key", "attention": True, "sentiment": True},
        "stocktwits": {"label": "StockTwits", "state": "unavailable", "attention": True, "sentiment": True},
        "x": {"label": "X / Twitter", "state": "unavailable", "attention": True, "sentiment": True},
    }


def any_connected_with_data(conn) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM sentiment_observations LIMIT 1")
        return cur.fetchone() is not None


# ------------------------------------------------------------------ DB read/write

def record_observation(conn: psycopg.Connection, source, symbol, entity_id, window_end, window_hours,
                       mentions, baseline=None, sentiment=None, bots_filtered=0, meta=None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO sentiment_observations
                 (source, symbol, entity_id, window_end, window_hours, mentions, baseline,
                  sentiment, bots_filtered, knowable_time, meta)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (source, symbol, window_end) DO UPDATE SET
                 mentions=EXCLUDED.mentions, baseline=EXCLUDED.baseline, sentiment=EXCLUDED.sentiment,
                 bots_filtered=EXCLUDED.bots_filtered, meta=EXCLUDED.meta""",
            (source, symbol.upper(), entity_id, window_end, window_hours, mentions, baseline,
             sentiment, bots_filtered, window_end, Json(meta or {})))
    conn.commit()


def tracked_symbols(conn: psycopg.Connection, limit=80) -> list[tuple]:
    """The ingestion universe: the most recently-converged issuers that resolve to a ticker (the
    names that matter), as (entity_id, name, symbol)."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT DISTINCT ON (c.issuer_entity) c.issuer_entity, e.name,
                 (SELECT symbol FROM security_map m WHERE m.entity_id=c.issuer_entity
                    AND m.source='sec_company_tickers' ORDER BY confidence DESC LIMIT 1) sym
               FROM signal_clusters c JOIN entities e ON e.id=c.issuer_entity
               ORDER BY c.issuer_entity, c.as_of DESC""")
        rows = [(r[0], r[1], r[2]) for r in cur.fetchall() if r[2]]
    return rows[:limit]


def _group(rows) -> dict:
    grouped: dict = {}
    for symbol, source, mentions, baseline, sentiment, bots, name in rows:
        g = grouped.setdefault(symbol, {"name": name, "obs": []})
        g["obs"].append({"source": source, "mentions": mentions, "baseline": baseline,
                         "sentiment": sentiment, "bots_filtered": bots})
    return grouped


_BOARD_SQL = ("SELECT o.symbol, o.source, o.mentions, o.baseline, o.sentiment, o.bots_filtered, e.name "
              "FROM sentiment_observations o LEFT JOIN entities e ON e.id=o.entity_id "
              "WHERE o.window_end >= now() - make_interval(hours => %s)")


def trending_board(conn: psycopg.Connection, hours=DEFAULT_WINDOW_HOURS, min_mentions=MIN_MENTIONS,
                   limit=25) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(_BOARD_SQL, (hours,))
        rows = cur.fetchall()
    return trending(_group(rows), min_mentions=min_mentions, limit=limit)


def symbol_sentiment(conn: psycopg.Connection, symbol, hours=168) -> dict | None:
    symbol = symbol.upper()
    with conn.cursor() as cur:
        cur.execute(_BOARD_SQL.replace("WHERE", "WHERE o.symbol=%s AND") + " ORDER BY o.window_end DESC",
                    (symbol, hours))
        rows = cur.fetchall()
    if not rows:
        return None
    return score_symbol(symbol, rows[0][6], _group(rows)[symbol]["obs"])
