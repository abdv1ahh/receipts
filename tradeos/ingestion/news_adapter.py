"""Adapt the existing news layer onto the event spine.

`news_items` is the raw US-markets news layer and keeps its job — eleven surfaces read it and
none of them should notice this exists. This module projects those rows into `events` so the
spine has real, dense data from day one rather than waiting for the new sources to accumulate,
and so a story that arrives from both CNBC and GDELT clusters as one happening instead of two.

It is deliberately one-directional: news_items -> events, never the reverse. If this file were
deleted tomorrow the news surface would carry on working.
"""
from __future__ import annotations

import logging

from .. import spine

log = logging.getLogger("tradeos.ingestion.news_adapter")

# news_items.category is a markets taxonomy ('earnings', 'ma', 'officer_change', 'guidance',
# 'macro', 'general'). The spine's is a world-event taxonomy. Map what maps; let the spine's own
# classifier read the headline for the rest rather than forcing a bad fit.
_CATEGORY = {
    "earnings": "earnings",
    "ma": "corporate",
    "officer_change": "corporate",
    "guidance": "earnings",
    "macro": "macro",
    "markets": None,          # too broad to be a category — let the cue table decide
    "general": None,
}

# Everything in news_items is US-registrant filings or US financial media.
_DEFAULT_GEO = ["US"]


def to_event(row: dict) -> dict:
    """One news_item as a spine event. The ticker it was hung on becomes an entity, so the spine
    can join a company story to a country story without news_items knowing about entities."""
    category = _CATEGORY.get(row.get("category") or "")
    entities = [{"kind": "ticker", "value": s, "confidence": 1.0}
                for s in (row.get("symbols") or []) if s]
    return {
        "source": row["source"],
        "external_id": row["external_id"],
        "source_url": row["url"],
        "published_at": row.get("published_at"),
        "knowable_time": row["knowable_time"],
        "title": row["headline"],
        "body": row.get("summary"),
        "language": "en",
        "entities": entities,
        "geo": _DEFAULT_GEO,
        "category": category or spine.classify(row["headline"], row.get("summary")),
        "raw_payload": {"news_id": row["id"], "meta": row.get("meta") or {}},
    }


def backfill(conn, since_hours: int | None = None, limit: int = 5000) -> dict:
    """Project news_items into the spine. Idempotent — the spine upserts on (source, external_id),
    which for these rows is exactly news_items' own unique key, so re-running updates in place.

    `since_hours=None` does the whole table (the one-time bootstrap); the scheduler passes a small
    window so the recurring job stays cheap."""
    where, params = "", []
    if since_hours is not None:
        where = "WHERE n.knowable_time >= now() - make_interval(hours => %s)"
        params.append(since_hours)
    with conn.cursor() as cur:
        cur.execute(
            f"""SELECT n.id, n.source, n.external_id, n.url, n.headline, n.summary, n.category,
                       n.published_at, n.knowable_time, n.meta,
                       coalesce(array_agg(e.symbol) FILTER (WHERE e.symbol IS NOT NULL), '{{}}')
                  FROM news_items n
                  LEFT JOIN news_item_entities e ON e.news_id = n.id
                  {where}
                 GROUP BY n.id
                 ORDER BY n.knowable_time
                 LIMIT %s""",
            (*params, limit))
        cols = ("id", "source", "external_id", "url", "headline", "summary", "category",
                "published_at", "knowable_time", "meta", "symbols")
        rows = [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]
    if not rows:
        return {"events": 0, "clusters": 0}
    out = spine.ingest_events(conn, [to_event(r) for r in rows])
    log.info("news_adapter: projected %d news items -> %s", len(rows), out)
    return out
