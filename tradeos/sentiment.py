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
    """Score one symbol from at most one CURRENT observation per source (see trending_board).

    Two things this must not do, both of which it used to. It must not sum repeated snapshots of
    the same underlying measure — Wikipedia writes yesterday's pageview total every run, so adding
    up a window of runs produced "7,547 mentions" for a name that gets 312 views a day. And it must
    not divide a total that includes baseline-less sources by a total that excludes them: that
    alone turned a 1.01x name into a 5.48x "spike" and put common-sounding tickers at the top of
    the board. Velocity is now a mention-weighted mean of per-source ratios over exactly the
    sources that have a baseline, and a source with no history contributes attention but never
    velocity."""
    mentions = sum(o.get("mentions", 0) for o in obs)
    with_base = [o for o in obs if (o.get("baseline") or 0) > 0]
    base_mentions = sum(o.get("mentions", 0) for o in with_base)
    baseline = sum(o["baseline"] for o in with_base) or None
    velocity = None
    if with_base and base_mentions:
        weighted = sum(o["mentions"] * (o["mentions"] / o["baseline"]) for o in with_base)
        velocity = round(weighted / base_mentions, 2)
    return {"symbol": symbol, "name": name or symbol, "mentions": mentions,
            "attention": attention_score(base_mentions or mentions, baseline),
            "sentiment": blend_sentiment(obs),
            "velocity": velocity,
            "sources": sorted({o["source"] for o in obs}),
            "is_new": baseline is None, "flags": manipulation_flag(obs)}


def trending(grouped, min_mentions=MIN_MENTIONS, limit=25) -> list[dict]:
    """Rank symbols by attention, keeping only those above the mention floor. `grouped` is
    {symbol: {"name": .., "obs": [..]}} — the pure ranking core the DB layer feeds."""
    scored = []
    for sym, g in grouped.items():
        row = score_symbol(sym, g.get("name"), g["obs"])
        classes = g.get("share_classes") or [sym]
        if len(classes) > 1:
            # Named, not hidden: a reader who searches GOOGL must be able to see why the board says
            # GOOG, and the merged count only makes sense once you know what was merged.
            row["share_classes"] = classes
        scored.append(row)
    scored = [x for x in scored if x["mentions"] >= min_mentions]
    scored.sort(key=lambda x: (x["attention"], x["mentions"]), reverse=True)
    return scored[:limit]


# ------------------------------------------------------------------ honest source status

# Which of the catalogued sources feed the attention board, and whether each measures mood as well
# as volume. `attention` = measures public attention; `sentiment` = measures mood.
ATTENTION_SOURCES = {
    "wikipedia": {"attention": True, "sentiment": False},
    "hn": {"attention": True, "sentiment": False},
    "reddit": {"attention": True, "sentiment": True},
    "youtube": {"attention": True, "sentiment": True},
    "stocktwits": {"attention": True, "sentiment": True},
    "x": {"attention": True, "sentiment": True},
}


def sources_status() -> dict:
    """The attention board's source strip, derived from the one source registry (sources.py) so
    there is no second place to update when a source's state changes. Each entry carries what it
    would add and where its free key comes from, so a disconnected source is an explained gap with
    a next step rather than a bare 'N/A'."""
    from . import sources
    out = {}
    for key, caps in ATTENTION_SOURCES.items():
        g = sources.gate(key)
        out[key] = {"label": g["label"], "state": g["state"], **caps,
                    "powers": g["powers"], "note": g["note"], "signup_url": g.get("signup_url"),
                    "env": g.get("env", [])}
    return out


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


def _primary(symbols: list[str]) -> str:
    """The ticker to display for a company with several share classes.

    Shortest, then alphabetical: GOOG over GOOGL, FOX over FOXA, BRK.A over BRK.B. Deterministic on
    purpose — the obvious alternative, "whichever class has more mentions today", would let a board
    row rename itself between refreshes, which reads as a bug even when the number is right."""
    return sorted(symbols, key=lambda s: (len(s), s))[0]


def _group(rows) -> dict:
    """Group observations by COMPANY, not by ticker.

    Alphabet files as one issuer and trades as GOOG and GOOGL, so keying on the symbol put it on
    the attention board twice with its attention split between the rows — each half then measured
    against its own baseline, so a genuine spike could miss the mention floor in both. Same for
    FOX/FOXA and every dual-class listing.

    `entity_id` is the company; it is already resolved on the observation. Rows without one (a
    ticker the resolver has not mapped) fall back to the symbol, which is the old behaviour and
    correct for them — an unmapped ticker has no company to be merged into.
    """
    by_company: dict = {}
    for symbol, source, mentions, baseline, sentiment, bots, name, entity_id in rows:
        key = ("e", entity_id) if entity_id is not None else ("s", symbol)
        g = by_company.setdefault(key, {"name": name, "symbols": [], "by_source": {}})
        if symbol not in g["symbols"]:
            g["symbols"].append(symbol)
        g["name"] = g["name"] or name
        # Merge per source: attention on Alphabet is attention on Alphabet, whichever class carried
        # the mention. Baselines add too, or a summed count would be compared against half a base.
        o = g["by_source"].setdefault(source, {"source": source, "mentions": 0, "baseline": None,
                                               "sentiment": None, "bots_filtered": 0})
        o["mentions"] += mentions or 0
        if baseline is not None:
            o["baseline"] = (o["baseline"] or 0) + baseline
        if sentiment is not None:
            # Mention-weighted, so the bigger class carries proportionally more of the mood.
            prior_w = o.get("_sw", 0)
            o["_sw"] = prior_w + (mentions or 0)
            o["sentiment"] = (((o["sentiment"] or 0) * prior_w) + sentiment * (mentions or 0)) / (o["_sw"] or 1)
        o["bots_filtered"] = (o["bots_filtered"] or 0) + (bots or 0)

    grouped: dict = {}
    for g in by_company.values():
        display = _primary(g["symbols"])
        obs = [{k: v for k, v in o.items() if not k.startswith("_")} for o in g["by_source"].values()]
        grouped[display] = {"name": g["name"], "obs": obs,
                            # Every ticker folded in, so the interface can say so rather than
                            # silently dropping one.
                            "share_classes": sorted(g["symbols"])}
    return grouped


# The CURRENT reading per (symbol, source), not every reading in the window. Each source writes a
# snapshot of the same measure on every run, so taking more than the latest one double-counts.
_BOARD_SQL = """
    SELECT DISTINCT ON (o.symbol, o.source)
           o.symbol, o.source, o.mentions, o.baseline, o.sentiment, o.bots_filtered, e.name,
           o.entity_id
      FROM sentiment_observations o
      LEFT JOIN entities e ON e.id = o.entity_id
     WHERE o.window_end >= now() - make_interval(hours => %s)
       AND (%s::text IS NULL OR o.symbol = %s)
     ORDER BY o.symbol, o.source, o.window_end DESC
"""


def _board_rows(conn: psycopg.Connection, hours: int, symbol: str | None = None):
    with conn.cursor() as cur:
        cur.execute(_BOARD_SQL, (hours, symbol, symbol))
        return cur.fetchall()


def trending_board(conn: psycopg.Connection, hours=DEFAULT_WINDOW_HOURS, min_mentions=MIN_MENTIONS,
                   limit=25) -> list[dict]:
    return trending(_group(_board_rows(conn, hours)), min_mentions=min_mentions, limit=limit)


def symbol_sentiment(conn: psycopg.Connection, symbol, hours=168) -> dict | None:
    symbol = symbol.upper()
    rows = _board_rows(conn, hours, symbol)
    if not rows:
        return None
    # `_group` keys by the DISPLAY ticker of the company, which for GOOGL is GOOG — so indexing by
    # the requested symbol would KeyError on every non-primary share class. Find the group that
    # actually contains it, and answer under the symbol that was asked for.
    grouped = _group(rows)
    g = grouped.get(symbol) or next(
        (v for v in grouped.values() if symbol in (v.get("share_classes") or [])), None)
    if not g:
        return None
    out = score_symbol(symbol, g.get("name") or rows[0][6], g["obs"])
    if len(g.get("share_classes") or []) > 1:
        out["share_classes"] = g["share_classes"]
    return out
