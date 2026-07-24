"""Wikipedia pageview attention source (Social & Attention Intelligence, Milestone 2).

A company's Wikipedia pageviews are a clean, keyless, ToS-clean proxy for RETAIL ATTENTION — a spike in
views is a real, hard-to-manipulate signal that the public is suddenly looking a name up (used in
academic finance for exactly this). It measures attention, not sentiment, so we store sentiment NULL
(honest) — a sentiment-capable source (Reddit) fills that in.

Two allowlisted Wikimedia hosts: en.wikipedia.org (resolve company -> canonical article title, cached
in wiki_titles) and wikimedia.org (daily pageviews REST). Names that don't resolve are recorded as an
honest miss and skipped — never a fabricated title.
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote, urlparse

import httpx

from .. import sentiment

log = logging.getLogger("tradeos.attention.wiki")

WIKI_API = "https://en.wikipedia.org/w/api.php"
WIKI_API_HOST = "en.wikipedia.org"
PV_URL = ("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/"
          "en.wikipedia/all-access/all-agents/{title}/daily/{start}/{end}")
PV_HOST = "wikimedia.org"
# Wikimedia's UA policy rejects requests without an identifiable contact; a product URL satisfies it.
UA = {"User-Agent": "TradeOSS/1.0 (https://tradeos.app; market-attention research)"}


# ------------------------------------------------------------------ pure: velocity from a view series

def velocity_from_views(daily: list[int]) -> tuple[int, float | None]:
    """(recent, baseline) from a chronological daily-views series: the latest COMPLETE day's views vs
    the mean of the prior days. Returns (recent_views, baseline_or_None). Pure + offline-testable."""
    if not daily:
        return 0, None
    recent = daily[-1]
    prior = daily[:-1]
    baseline = round(sum(prior) / len(prior), 2) if prior else None
    return recent, baseline


# ------------------------------------------------------------------ title resolution (cached)

def _resolve_title(client: httpx.Client, company: str) -> str | None:
    """Canonical Wikipedia article title for a company (search, not opensearch, so we land on the real
    article rather than a redirect alias). None when nothing plausible matches."""
    r = client.get(WIKI_API, params={"action": "query", "list": "search", "srsearch": company,
                                      "srlimit": 1, "srnamespace": 0, "format": "json"})
    r.raise_for_status()
    hits = r.json().get("query", {}).get("search", [])
    return hits[0]["title"] if hits else None


def _titles_for(conn, client, universe) -> dict[str, tuple[int, str]]:
    """{symbol: (entity_id, title)} for the universe, resolving+caching misses in wiki_titles. An
    unresolved name is cached as resolved_ok=false so we don't retry it every run."""
    out: dict[str, tuple[int, str]] = {}
    with conn.cursor() as cur:
        cur.execute("SELECT symbol, entity_id, title, resolved_ok FROM wiki_titles")
        cache = {r[0]: (r[1], r[2], r[3]) for r in cur.fetchall()}
    for entity_id, name, symbol in universe:
        if symbol in cache:
            eid, title, ok = cache[symbol]
            if ok and title:
                out[symbol] = (entity_id or eid, title)
            continue
        title = None
        try:
            title = _resolve_title(client, (name or symbol).strip())
        except Exception as exc:
            log.warning("wiki title resolve failed for %s (%s)", symbol, type(exc).__name__)
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO wiki_titles (symbol, entity_id, title, resolved_ok, resolved_at)
                   VALUES (%s,%s,%s,%s, now())
                   ON CONFLICT (symbol) DO UPDATE SET entity_id=EXCLUDED.entity_id,
                       title=EXCLUDED.title, resolved_ok=EXCLUDED.resolved_ok, resolved_at=now()""",
                (symbol, entity_id, title, bool(title)))
        conn.commit()
        if title:
            out[symbol] = (entity_id, title)
        time.sleep(0.2)   # be polite to the search API
    return out


# ------------------------------------------------------------------ pageviews + ingest

def _pageviews(client: httpx.Client, title: str, days: int = 16) -> list[int]:
    end = date.today() - timedelta(days=1)          # yesterday = last complete day
    start = end - timedelta(days=days)
    url = PV_URL.format(title=quote(title.replace(" ", "_"), safe=""),
                        start=start.strftime("%Y%m%d"), end=end.strftime("%Y%m%d"))
    if urlparse(url).hostname != PV_HOST:
        raise ValueError("wiki pageviews host allowlist violation")
    r = client.get(url)
    if r.status_code == 404:                          # no pageview data for this article -> honest empty
        return []
    r.raise_for_status()
    return [int(i["views"]) for i in r.json().get("items", [])]


def ingest(conn, universe, days: int = 16) -> int:
    """Record a Wikipedia attention observation per resolvable name: latest-day views (mentions) vs the
    trailing daily mean (baseline), which the velocity score turns into an attention reading."""
    if urlparse(WIKI_API).hostname != WIKI_API_HOST:
        raise ValueError("wiki api host allowlist violation")
    now = datetime.now(timezone.utc)
    written = 0
    with httpx.Client(timeout=20.0, headers=UA, follow_redirects=True) as client:
        titles = _titles_for(conn, client, universe)
        for symbol, (entity_id, title) in titles.items():
            try:
                daily = _pageviews(client, title, days=days)
            except Exception as exc:
                log.warning("wiki pageviews failed for %s (%s)", symbol, type(exc).__name__)
                continue
            recent, baseline = velocity_from_views(daily)
            if recent <= 0 and not baseline:
                continue                                  # no data -> skip, never fabricate
            sentiment.record_observation(conn, "wikipedia", symbol, entity_id, now, 24,
                                         recent, baseline=baseline, sentiment=None,
                                         meta={"title": title, "series_days": len(daily)})
            written += 1
            time.sleep(0.15)
    return written
