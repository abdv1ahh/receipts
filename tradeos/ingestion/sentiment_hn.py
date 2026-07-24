"""Hacker News (Algolia) sentiment source — free, keyless, ToS-clean (Slice H).

Counts recent public mentions of a company/ticker plus a trailing baseline, for an attention-velocity
score. HN carries no reliable per-item sentiment label, so sentiment is left NULL (honest) — a
sentiment-capable source (Reddit/YouTube) fills that in when the operator connects one. The host is
allowlisted (SSRF defense) and a User-Agent is declared, matching the SEC/FINRA/Tiingo clients.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import httpx

from .. import sentiment

log = logging.getLogger("tradeos.sentiment.hn")

HN_HOST = "hn.algolia.com"
HN_URL = "https://hn.algolia.com/api/v1/search_by_date"


def _count(client: httpx.Client, query: str, since_ts: int, until_ts: int | None = None) -> int:
    nf = f"created_at_i>{since_ts}" + (f",created_at_i<{until_ts}" if until_ts else "")
    r = client.get(HN_URL, params={"query": query, "tags": "(story,comment)",
                                   "numericFilters": nf, "hitsPerPage": 0})
    r.raise_for_status()
    return int(r.json().get("nbHits", 0))


def ingest_hn(conn, universe, window_hours: int = 48, baseline_days: int = 14) -> int:
    """For each (entity_id, name, symbol), record current-window mentions and a trailing baseline.
    Queries by company name (more precise than a short ticker). Returns rows written."""
    if urlparse(HN_URL).hostname != HN_HOST:
        raise ValueError("HN host allowlist violation")
    now = datetime.now(timezone.utc)
    win_start = int((now - timedelta(hours=window_hours)).timestamp())
    base_start = int((now - timedelta(days=baseline_days)).timestamp())
    windows = max(1.0, (baseline_days * 24 - window_hours) / window_hours)
    written = 0
    with httpx.Client(timeout=20.0, headers={"User-Agent": "TradeOSS/sentiment (contact via app)"}) as client:
        for entity_id, name, symbol in universe:
            query = (name or symbol or "").strip()
            if not query:
                continue
            try:
                mentions = _count(client, query, win_start)
                base_total = _count(client, query, base_start, win_start)
            except Exception as exc:  # transient/network -> skip this symbol, never fabricate
                log.warning("HN fetch failed for %s (%s)", symbol, type(exc).__name__)
                continue
            baseline = round(base_total / windows, 2) if base_total else None
            sentiment.record_observation(conn, "hn", symbol, entity_id, now, window_hours,
                                         mentions, baseline=baseline, sentiment=None,
                                         meta={"query": query})
            written += 1
            time.sleep(0.3)  # be polite to the free API
    return written
