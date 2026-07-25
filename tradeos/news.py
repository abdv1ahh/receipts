"""News Intelligence read + scoring layer (parallel to sentiment.py).

Two honest halves:
  * DETERMINISTIC impact — intrinsic newsworthiness of an item is a pure function of its category,
    whether smart money is already converging on the name, and whether it is directly about the
    company (an 8-K) or merely mentions it. This number is Signal-plane discipline: reproducible,
    never a model's opinion. The AI plane may explain it, never invent it.
  * Read helpers + honest source status the API and the Morning Brief consume.
"""
from __future__ import annotations

from datetime import UTC, datetime

import psycopg

from .ingestion.news_rss import FEEDS

# Intrinsic newsworthiness by category (0..100 before adjustments). Ordered by how much a category
# typically moves a name: distress/M&A/earnings/guidance high; housekeeping low.
CATEGORY_WEIGHT = {
    "distress": 90, "ma": 85, "guidance": 78, "earnings": 72, "macro": 66,
    "officer_change": 55, "regulatory": 50, "agreement": 50, "financing": 46,
    "markets": 40, "disclosure": 36, "governance": 32, "general": 30,
}
SIGNAL_BONUS = 15          # smart money already converging on this name -> the news matters more
MENTION_DISCOUNT = 8       # 'mentioned' in a market story < 'primary' subject of an 8-K


def intrinsic_impact(category: str | None, has_signal: bool, relation: str = "primary") -> int:
    """Deterministic 0..100 impact. Pure — the analyst cites this, never overrides it."""
    base = CATEGORY_WEIGHT.get(category or "general", 30)
    if has_signal:
        base += SIGNAL_BONUS
    if relation == "mentioned":
        base -= MENTION_DISCOUNT
    return max(0, min(100, base))


RANK_HALF_LIFE_H = 36.0    # slow enough that a day-old material event still outranks fresh low-impact noise


def rank_value(impact: int, knowable: datetime, now: datetime | None = None) -> float:
    """Read-time ranking = intrinsic impact tapered by age. Keeps the brief fresh without letting
    recency rewrite intrinsic importance — a 36h half-life keeps yesterday's earnings above today's
    lifestyle column."""
    now = now or datetime.now(UTC)
    age_h = max(0.0, (now - knowable).total_seconds() / 3600.0)
    return round(impact * (0.5 ** (age_h / RANK_HALF_LIFE_H)), 3)


# ------------------------------------------------------------------ honest source status

def sources_status(conn: psycopg.Connection) -> list[dict]:
    """What each news source is and whether it is live — derived from feed_health, never faked."""
    with conn.cursor() as cur:
        cur.execute("SELECT source, last_success_at, last_record_knowable, records_total FROM feed_health")
        health = {r[0]: {"last_success": r[1], "freshest": r[2], "total": r[3]} for r in cur.fetchall()}
    out = [{"key": "sec/8-k", "label": "SEC 8-K material events", "kind": "primary_source",
            "state": "connected", **_health_of(health, "sec/8-k")}]
    for f in FEEDS:
        out.append({"key": f"rss/{f.key}", "label": f.label, "kind": "rss",
                    "state": "connected", **_health_of(health, f"rss/{f.key}")})
    return out


def _health_of(health: dict, source: str) -> dict:
    h = health.get(source)
    if not h:
        return {"state": "idle", "freshest": None, "records_total": 0}
    return {"freshest": h["freshest"].isoformat() if h["freshest"] else None,
            "records_total": h["total"]}


# ------------------------------------------------------------------ read layer

_SIGNAL_SYMS_SQL = """
    SELECT DISTINCT (SELECT symbol FROM security_map m WHERE m.entity_id=c.issuer_entity
                       AND m.source='sec_company_tickers' ORDER BY confidence DESC LIMIT 1) sym
    FROM signal_clusters c
    WHERE c.as_of=(SELECT max(as_of) FROM signal_clusters) AND c.confidence_bucket IN ('medium','high')
"""


def signal_symbols(conn: psycopg.Connection) -> set[str]:
    """Tickers with an active medium+ convergence signal at the latest as_of — the smart-money overlap."""
    with conn.cursor() as cur:
        cur.execute(_SIGNAL_SYMS_SQL)
        return {r[0] for r in cur.fetchall() if r[0]}


def _rows_to_items(rows, sig_syms: set[str]) -> list[dict]:
    now = datetime.now(UTC)
    items = []
    for (nid, source, url, headline, summary, category, knowable, _meta,
         symbols, impact, why, confidence, sources_json, model_id, used_template) in rows:
        syms = [s for s in (symbols or []) if s]
        has_sig = any(s in sig_syms for s in syms)
        # stored analysis wins; else deterministic intrinsic impact so ranking works pre-analysis
        eff_impact = impact if impact is not None else intrinsic_impact(category, has_sig)
        items.append({
            "id": nid, "source": source, "url": url, "headline": headline, "summary": summary,
            "category": category, "knowable_time": knowable.isoformat() if knowable else None,
            "symbols": syms, "has_signal": has_sig, "impact": eff_impact,
            "why_it_matters": why, "confidence": confidence, "cited_sources": sources_json or [],
            "analyzed": impact is not None, "ai_generated": bool(impact is not None and not used_template),
            "model_id": model_id, "rank": rank_value(eff_impact, knowable, now) if knowable else 0,
        })
    items.sort(key=lambda x: x["rank"], reverse=True)
    return items


_SELECT = """
    SELECT n.id, n.source, n.url, n.headline, n.summary, n.category, n.knowable_time, n.meta,
           array_agg(DISTINCT e.symbol) FILTER (WHERE e.symbol IS NOT NULL),
           a.impact_score, a.why_it_matters, a.confidence, a.sources, a.model_id, a.used_template
    FROM news_items n
    LEFT JOIN news_item_entities e ON e.news_id=n.id
    LEFT JOIN news_analysis a ON a.news_id=n.id
"""
_GROUP = (" GROUP BY n.id, a.impact_score, a.why_it_matters, a.confidence, a.sources, "
          "a.model_id, a.used_template")


def ranked_news(conn: psycopg.Connection, symbol: str | None = None, category: str | None = None,
                hours: int = 72, limit: int = 40) -> list[dict]:
    """Impact-ranked recent news, optionally filtered to a symbol or category."""
    sig = signal_symbols(conn)
    where = ["n.knowable_time >= now() - make_interval(hours => %s)"]
    params: list = [hours]
    if symbol:
        where.append("n.id IN (SELECT news_id FROM news_item_entities WHERE symbol=%s)")
        params.append(symbol.upper())
    if category:
        where.append("n.category=%s")
        params.append(category)
    with conn.cursor() as cur:
        cur.execute(_SELECT + " WHERE " + " AND ".join(where) + _GROUP, params)
        rows = cur.fetchall()
    return _rows_to_items(rows, sig)[:limit]


def get_item(conn: psycopg.Connection, news_id: int) -> dict | None:
    sig = signal_symbols(conn)
    with conn.cursor() as cur:
        cur.execute(_SELECT + " WHERE n.id=%s" + _GROUP, (news_id,))
        rows = cur.fetchall()
    items = _rows_to_items(rows, sig)
    return items[0] if items else None
