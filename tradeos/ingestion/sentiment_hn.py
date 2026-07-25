"""Hacker News (Algolia) sentiment source — free, keyless, ToS-clean (Slice H).

Counts recent public mentions of a company/ticker plus a trailing baseline, for an attention-velocity
score. HN carries no reliable per-item sentiment label, so sentiment is left NULL (honest) — a
sentiment-capable source (Reddit/YouTube) fills that in when the operator connects one. The host is
allowlisted (SSRF defense) and a User-Agent is declared, matching the SEC/FINRA/Tiingo clients.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import httpx

from .. import sentiment

log = logging.getLogger("tradeos.sentiment.hn")

HN_HOST = "hn.algolia.com"
HN_URL = "https://hn.algolia.com/api/v1/search_by_date"

# Legal-entity noise. "NVIDIA CORP" as a phrase matches nothing on HN; "Nvidia" matches everything
# about it, which is what a mention count is supposed to measure.
_SUFFIX = re.compile(
    r"[\s,]+(?:corp(?:oration)?|inc(?:orporated)?|incorporated|company|co|holdings?|group|"
    r"l\.?p\.?|llc|ltd|limited|plc|n\.?v\.?|s\.?a\.?|a\.?g\.?|trust|the)\b\.?",
    re.IGNORECASE)
_PUNCT = re.compile(r"[^\w\s&.-]")

# Company names that are also ordinary English words. Searching the bare word counts every HN
# discussion of the object, not the company: "Ball Corp" scored 6,757 mentions in a window where
# Nvidia scored 5,303. For these, the legal suffix is what makes the phrase distinctive, so it is
# kept. A short explicit table beats a cleverer heuristic here.
AMBIGUOUS = {
    "ball", "pool", "dover", "fix", "now", "star", "target", "gap", "block", "match", "shell",
    "square", "stripe", "apple", "amazon", "oracle", "arrow", "eagle", "hope", "national",
    "general", "union", "capital", "first", "public", "global", "summit", "pioneer", "liberty",
    "sun", "moon", "crown", "diamond", "phoenix", "atlas", "olympic", "cabot", "pinnacle",
}


def search_phrase(name: str | None, symbol: str | None = None) -> str | None:
    """The exact phrase to count mentions of, quoted for Algolia's advanced syntax, or None when
    nothing distinctive is left. Pure and offline-testable."""
    raw = (name or "").strip()
    if not raw:
        return f'"{symbol}"' if symbol else None
    full = re.sub(r"\s+", " ", _PUNCT.sub(" ", raw)).strip(" .,&-")
    core = re.sub(r"\s+", " ", _SUFFIX.sub("", full)).strip(" .,&-")
    if not core:
        return f'"{full}"' if full else None
    # One ordinary word on its own is not a company mention; keep the full legal name instead.
    if len(core.split()) == 1 and core.lower() in AMBIGUOUS:
        return f'"{full}"'
    return f'"{core}"'


def _count(client: httpx.Client, query: str, since_ts: int, until_ts: int | None = None) -> int:
    """Exact-phrase mention count. `advancedSyntax` is what makes the quotes mean "this phrase"
    rather than "any of these words" — without it the count is a fuzzy OR and is meaningless."""
    nf = f"created_at_i>{since_ts}" + (f",created_at_i<{until_ts}" if until_ts else "")
    r = client.get(HN_URL, params={"query": query, "tags": "(story,comment)",
                                   "numericFilters": nf, "hitsPerPage": 0,
                                   "advancedSyntax": "true"})
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
            query = search_phrase(name, symbol)
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
