"""Social & Attention Intelligence read/enrich layer (Milestone 2).

Turns the raw attention board (sentiment.trending_board — velocity vs a name's own baseline, honest
manipulation flags) into intelligence by answering "why": for the top movers it connects the attention
spike to a recent NEWS catalyst (Milestone 1) and phrases it via the guarded analyst plane. The board's
"why" uses the deterministic template so the endpoint stays instant and always available; the per-symbol
deep-dive can use the model when configured.
"""
from __future__ import annotations

import psycopg

from . import news, sentiment
from .intelligence import analyst


def attention_universe(conn, base):
    """The signal universe plus every symbol with recent NEWS, so Wikipedia/HN attention overlaps the
    news items — that overlap is what lets the analyst connect an attention spike to its catalyst.
    `base` is a list of (entity_id, name, symbol) tuples (e.g. sentiment.tracked_symbols)."""
    seen = {s for _, _, s in base}
    uni = list(base)
    with conn.cursor() as cur:
        cur.execute(
            """SELECT DISTINCT e.symbol, ent.id, ent.name FROM news_item_entities e
               JOIN news_items n ON n.id = e.news_id
               LEFT JOIN entities ent ON ent.id = e.entity_id
               WHERE n.knowable_time >= now() - interval '12 days'""")
        for sym, eid, name in cur.fetchall():
            if sym and sym not in seen:
                seen.add(sym)
                uni.append((eid, name or sym, sym))
    return uni


def _attach(conn, row: dict, hours: int, limit: int, provider: str):
    recent = news.ranked_news(conn, symbol=row["symbol"], hours=hours, limit=limit)
    row["why"] = analyst.attention_why(row["symbol"], row, recent, provider=provider)
    row["news"] = [{"id": n["id"], "headline": n["headline"], "url": n["url"], "category": n["category"]}
                   for n in recent[:3]]
    return row


def board(conn: psycopg.Connection, hours: int = 72, limit: int = 20, enrich_top: int = 8) -> list[dict]:
    """Attention leaderboard with a deterministic 'why' (attention spike -> likely news catalyst) on the
    top movers. Template-only so the board is instant; the deep-dive is where the model can weigh in."""
    rows = sentiment.trending_board(conn, hours=hours, min_mentions=3, limit=limit)
    for i, r in enumerate(rows):
        if i < enrich_top:
            _attach(conn, r, hours=168, limit=3, provider="template")
        else:
            r["why"], r["news"] = None, []
    return rows


def symbol_detail(conn: psycopg.Connection, symbol: str, provider: str | None = None) -> dict | None:
    """One name's attention + sentiment across sources, its recent news, and a (model-capable) 'why'."""
    d = sentiment.symbol_sentiment(conn, symbol)
    if not d:
        return None
    return _attach(conn, d, hours=240, limit=5, provider=(provider or "").lower() or None)
