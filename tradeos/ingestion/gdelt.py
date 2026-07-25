"""GDELT DOC 2.0 — the global news backbone.

GDELT machine-codes worldwide news with the source country and language attached, needs no key,
and covers regions no RSS list this project could maintain would reach. That is what makes the
product's "what does this mean for someone in Sharjah" premise possible at all: the existing feeds
are CNBC, the Fed and the SEC, which is a US-markets view of the world.

Measured against the live API on 2026-07-25:
  * keyless, JSON, returns url/title/domain/language/sourcecountry/seendate per article;
  * rate limited hard — a burst of three requests earned a 429, and the limiter stays angry for a
    while afterwards. It wants roughly one request every five seconds and no concurrency.

So this adapter paces itself deliberately and records every call in source_calls. Being a good
citizen of a free API is not politeness here; it is the difference between having the source and
losing it.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx

from .. import spine

log = logging.getLogger("tradeos.ingestion.gdelt")

HOST = "api.gdeltproject.org"
URL = "https://api.gdeltproject.org/api/v2/doc/doc"
UA = {"User-Agent": "Rhumb/1.0 (world-event research; contact via the application)"}

MIN_INTERVAL_S = 6.0        # measured: faster than ~5s earns a 429
_last_call = 0.0

# What the spine is actually watching for. Each is one paced request, so this list is a quota
# budget as much as a topic list — keep it short and consequential. Queries are GDELT syntax.
QUERIES: list[tuple[str, str]] = [
    ("monetary_policy", '("interest rate" OR "central bank" OR "monetary policy") sourcelang:english'),
    ("conflict",        '("ceasefire" OR "airstrike" OR "military operation") sourcelang:english'),
    ("supply_chain",    '("shipping lane" OR "port closure" OR "export ban" OR "supply chain") sourcelang:english'),
    ("energy",          '("oil production" OR "OPEC" OR "natural gas supply") sourcelang:english'),
    ("trade_policy",    '("tariff" OR "trade deal" OR "sanctions on") sourcelang:english'),
]

# GDELT returns a country NAME, not a code. Only the ones our queries actually surface are mapped;
# an unmapped country is dropped rather than guessed, so `geo` never contains an invented code.
_COUNTRY_CODE = {
    "united states": "US", "united kingdom": "GB", "china": "CN", "japan": "JP", "germany": "DE",
    "france": "FR", "india": "IN", "russia": "RU", "brazil": "BR", "canada": "CA",
    "australia": "AU", "italy": "IT", "spain": "ES", "netherlands": "NL", "switzerland": "CH",
    "united arab emirates": "AE", "saudi arabia": "SA", "qatar": "QA", "kuwait": "KW",
    "israel": "IL", "turkey": "TR", "egypt": "EG", "iran": "IR", "iraq": "IQ",
    "south korea": "KR", "korea": "KR", "singapore": "SG", "hong kong": "HK", "taiwan": "TW",
    "indonesia": "ID", "malaysia": "MY", "thailand": "TH", "vietnam": "VN", "pakistan": "PK",
    "nigeria": "NG", "south africa": "ZA", "kenya": "KE", "mexico": "MX", "argentina": "AR",
    "chile": "CL", "colombia": "CO", "poland": "PL", "sweden": "SE", "norway": "NO",
    "denmark": "DK", "finland": "FI", "ireland": "IE", "belgium": "BE", "austria": "AT",
    "greece": "GR", "portugal": "PT", "ukraine": "UA", "new zealand": "NZ",
}

_LANG_CODE = {"english": "en", "chinese": "zh", "spanish": "es", "arabic": "ar", "french": "fr",
              "german": "de", "russian": "ru", "japanese": "ja", "portuguese": "pt",
              "italian": "it", "korean": "ko", "hindi": "hi", "turkish": "tr", "dutch": "nl"}


def country_code(name: str | None) -> str | None:
    """ISO alpha-2 for a GDELT country name, or None. Never guesses — an unmapped country is
    simply absent, because a wrong country code on the globe is worse than a missing one."""
    return _COUNTRY_CODE.get((name or "").strip().lower())


def language_code(name: str | None) -> str | None:
    return _LANG_CODE.get((name or "").strip().lower())


def parse_seendate(s: str | None) -> datetime | None:
    """GDELT's compact timestamp, '20260725T023000Z', to an aware datetime."""
    if not s:
        return None
    m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z", s.strip())
    if not m:
        return None
    y, mo, d, h, mi, sec = (int(x) for x in m.groups())
    try:
        return datetime(y, mo, d, h, mi, sec, tzinfo=UTC)
    except ValueError:
        return None


def to_event(article: dict, category: str) -> dict | None:
    """One GDELT article as a spine event. Returns None for anything without the fields that make
    it usable, rather than storing a placeholder."""
    url = (article.get("url") or "").strip()
    title = (article.get("title") or "").strip()
    seen = parse_seendate(article.get("seendate"))
    if not url or not title or seen is None:
        return None
    geo = country_code(article.get("sourcecountry"))
    return {
        "source": "gdelt",
        "external_id": url,                       # GDELT's stable identity for an article
        "source_url": url,
        "published_at": seen,
        "knowable_time": seen,                    # when GDELT saw it public is when it was knowable
        "title": title,
        "language": language_code(article.get("language")),
        "geo": [geo] if geo else [],
        "category": category,
        "raw_payload": article,                   # kept whole, so the engine can be rerun
    }


def _record_call(conn, status: int, ms: int, ok: bool) -> None:
    """Endpoint PATH only — never the query string. See the note in scheduler.redact()."""
    with conn.cursor() as cur:
        cur.execute("INSERT INTO source_calls (source, endpoint, status, duration_ms, ok) "
                    "VALUES ('gdelt', %s, %s, %s, %s)", (urlparse(URL).path, status, ms, ok))
    conn.commit()


def _fetch(client: httpx.Client, query: str, timespan: str, maxrecords: int) -> list[dict]:
    """One paced request. Raises on a non-200 so the caller can record and back off."""
    global _last_call
    wait = MIN_INTERVAL_S - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    if urlparse(URL).hostname != HOST:
        raise ValueError("gdelt host allowlist violation")
    resp = client.get(URL, params={"query": query, "mode": "artlist", "maxrecords": maxrecords,
                                   "format": "json", "timespan": timespan})
    _last_call = time.monotonic()
    resp.raise_for_status()
    # GDELT answers a malformed query with HTML and a 200, so never trust the status alone.
    if "json" not in resp.headers.get("content-type", ""):
        raise ValueError("gdelt returned a non-JSON body (usually a malformed query)")
    return resp.json().get("articles") or []


def ingest(conn, queries=None, timespan: str = "2h", maxrecords: int = 60) -> dict:
    """Pull each watched topic and push it through the spine. One request per query, paced.

    A 429 stops the whole pass rather than hammering on: the limiter stays angry for a while, and
    the next scheduled run is only minutes away. Losing one cycle is cheap; losing the source is
    not."""
    out: dict = {"events": 0, "clusters": 0, "queries": 0, "rate_limited": False}
    with httpx.Client(timeout=45.0, headers=UA, follow_redirects=True) as client:
        for category, query in (queries or QUERIES):
            t0 = time.monotonic()
            try:
                articles = _fetch(client, query, timespan, maxrecords)
            except httpx.HTTPStatusError as exc:
                ms = int((time.monotonic() - t0) * 1000)
                _record_call(conn, exc.response.status_code, ms, False)
                if exc.response.status_code == 429:
                    log.warning("gdelt rate limited on '%s'; stopping this pass", category)
                    out["rate_limited"] = True
                    break
                log.warning("gdelt %s failed for '%s'", exc.response.status_code, category)
                continue
            except Exception as exc:
                _record_call(conn, 0, int((time.monotonic() - t0) * 1000), False)
                log.warning("gdelt fetch failed for '%s' (%s)", category, type(exc).__name__)
                continue
            _record_call(conn, 200, int((time.monotonic() - t0) * 1000), True)
            out["queries"] += 1
            events = [e for e in (to_event(a, category) for a in articles) if e]
            res = spine.ingest_events(conn, events)
            out["events"] += res["events"]
            out["clusters"] += res["clusters"]
    return out
