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

MIN_INTERVAL_S = 6.0        # GDELT's own message asks for one request every 5 seconds
BACKOFF_HOURS = 6           # after a 429, stay away this long — see below
_last_call = 0.0

# A run of failures we cannot attribute is still a reason to stop knocking. Measured on this
# install: 30 calls on 2026-08-21, 25 on the 22nd, zero successes, and no backoff ever engaged
# because none of them recorded as a 429. Whatever the cause, the fifth consecutive failure is
# evidence enough to wait — shorter than the 429 penalty, because this is an unknown fault rather
# than a stated one and recovery should not be delayed six hours by a blip.
CONSECUTIVE_FAILURES = 5
UNKNOWN_FAULT_BACKOFF_HOURS = 1


class RateLimited(Exception):
    """GDELT refused on volume grounds.

    Its own answer to this is not consistent: sometimes HTTP 429, and sometimes **HTTP 200 carrying
    the same plain-text refusal**, with no content-type header at all. The second form used to fall
    into the generic exception handler and record as `status = 0`, which is 75% of this source's
    call history — so `_in_backoff`, which looks for 429, could not see the most common way GDELT
    says no. The fix is to recognise the refusal wherever it appears and record it as what it is;
    the backoff query then needs no widening, because the data it reads is finally true."""


# The refusal text, measured live on 2026-08-24 (HTTP 429, content-type absent, 444 bytes):
#   "Please limit requests to one every 5 seconds or contact ... for larger queries. All
#    high-traffic users should switch to our ngrams dataset ..."
_REFUSAL = re.compile(r"limit requests|high-traffic users|too many requests|rate limit", re.I)

# Measured over several hours on 2026-07-25: GDELT's throttle is keyed on the User-Agent and has a
# cumulative volume cap well beyond the published "one request every 5 seconds". Once a UA is
# penalised it stays penalised for hours, and every fresh UA string works once or twice before
# being penalised in turn.
#
# The conclusion matters more than the mechanism: rotating the User-Agent WOULD restore access, and
# we deliberately do not. That is evasion of a rate limit on a free service, it breaks the moment
# they tighten the check, and this project does not ship things that work by not being noticed. So
# the identifier stays honest and constant, and instead we back off hard and persistently — a
# penalised source is skipped entirely rather than re-hammered on every scheduler tick.


def _in_backoff(conn) -> tuple[float, str]:
    """(hours remaining before it is polite to try again, why). Persisted in source_calls rather
    than in memory, so a container restart cannot reset the penalty clock.

    Two rules, because there are two ways this source tells us to stop:

      a stated refusal   a 429 — now including the 200-with-a-refusal-body form, which `_fetch`
                         records as 429 rather than 0. This is the six-hour penalty.
      a run of silence   CONSECUTIVE_FAILURES failures with no success between them. This catches
                         a penalised User-Agent whose refusal we did not recognise, and anything
                         else that is simply not working. Shorter, because the cause is unknown.

    The second rule is the one that was missing. Without it the scheduler kept calling a source
    that had not returned a single success in three weeks."""
    with conn.cursor() as cur:
        cur.execute("""SELECT extract(epoch FROM now() - max(at)) / 3600.0
                         FROM source_calls WHERE source = 'gdelt' AND status = 429""")
        hours_since = cur.fetchone()[0]
        if hours_since is not None:
            remaining = max(0.0, BACKOFF_HOURS - float(hours_since))
            if remaining > 0:
                return remaining, f"rate limited {float(hours_since):.1f}h ago"

        # The last N calls: did every one of them fail, and how long ago was the newest. Both from
        # the database clock, in one statement, so this cannot disagree with itself.
        cur.execute("""SELECT bool_and(NOT ok), extract(epoch FROM now() - max(at)) / 3600.0,
                              count(*)
                         FROM (SELECT ok, at FROM source_calls WHERE source = 'gdelt'
                                ORDER BY at DESC LIMIT %s) recent""", (CONSECUTIVE_FAILURES,))
        all_failed, since, n = cur.fetchone()
    if all_failed and n >= CONSECUTIVE_FAILURES:
        remaining = max(0.0, UNKNOWN_FAULT_BACKOFF_HOURS - float(since))
        if remaining > 0:
            return remaining, f"{n} consecutive failures, none of them a 429"
    return 0.0, ""


def _next_start(conn, queries: list[tuple[str, str]]) -> int:
    """Index of the query this pass should begin with.

    A refusal ends the pass, and the list was walked from position zero every time, so the tail was
    never reached: `trade_policy` sat fifth and had **never once executed** in the source's life.
    GDELT's entire contribution to the corpus was queries one and two — 142 conflict events and 142
    monetary_policy events, and nothing else, ever.

    Starting at the least-recently-ATTEMPTED query is better than a blind counter because it is
    self-correcting: whatever got starved is by definition what runs next, and a pass that dies
    after one request still advances the rotation. A query never tried sorts first of all."""
    path = urlparse(URL).path
    with conn.cursor() as cur:
        cur.execute("""SELECT endpoint, max(at) FROM source_calls
                        WHERE source = 'gdelt' AND endpoint LIKE %s GROUP BY 1""", (f"{path} %",))
        attempted = {e.split(" ", 1)[1]: at for e, at in cur.fetchall() if " " in e}
    # (never attempted first, then oldest attempt first, then latest position first). Comparing the
    # flag before the timestamp keeps a None out of any `<` comparison. The position tiebreak
    # matters on the very first pass after this ships: no call in `source_calls` carries a topic
    # yet, so every query looks equally untried, and the tail is exactly the part we know was
    # starved — `trade_policy` should not have to wait another rotation for its first turn ever.
    return min(range(len(queries)),
               key=lambda i: (attempted.get(queries[i][0]) is not None,
                              attempted.get(queries[i][0]) or 0, -i))

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


def _record_call(conn, status: int, ms: int, ok: bool, category: str = "") -> None:
    """Endpoint PATH plus the topic — never the query string. See the note in scheduler.redact().

    The topic is our own label, not GDELT syntax and not a credential, and recording it is what
    makes `_next_start` possible. It also makes the starvation visible after the fact: until now
    `source_calls` could say a gdelt call failed but not WHICH query failed, which is exactly why
    nobody noticed that three of the five had never run."""
    endpoint = f"{urlparse(URL).path} {category}" if category else urlparse(URL).path
    with conn.cursor() as cur:
        cur.execute("INSERT INTO source_calls (source, endpoint, status, duration_ms, ok) "
                    "VALUES ('gdelt', %s, %s, %s, %s)", (endpoint, status, ms, ok))
    conn.commit()


def _fetch(client: httpx.Client, query: str, timespan: str, maxrecords: int) -> list[dict]:
    """One paced request. Raises on a refusal or a non-200 so the caller can record and back off."""
    global _last_call
    wait = MIN_INTERVAL_S - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    if urlparse(URL).hostname != HOST:
        raise ValueError("gdelt host allowlist violation")
    resp = client.get(URL, params={"query": query, "mode": "artlist", "maxrecords": maxrecords,
                                   "format": "json", "timespan": timespan})
    _last_call = time.monotonic()
    # GDELT answers a malformed query with HTML and a 200, so never trust the status alone — and it
    # answers an over-quota request with a plain-text refusal under EITHER 429 or 200. Read the body
    # before the status, or the 200-shaped refusal is recorded as an unknown fault and the backoff
    # never engages. `.text` is only touched when the body is not JSON.
    is_json = "json" in (resp.headers.get("content-type") or "")
    if resp.status_code == 429 or (not is_json and _REFUSAL.search(resp.text[:1000])):
        raise RateLimited(f"gdelt refused on volume (HTTP {resp.status_code})")
    resp.raise_for_status()
    if not is_json:
        raise ValueError("gdelt returned a non-JSON body (usually a malformed query)")
    return resp.json().get("articles") or []


def ingest(conn, queries=None, timespan: str = "2h", maxrecords: int = 60) -> dict:
    """Pull each watched topic and push it through the spine. One request per query, paced.

    A refusal stops the whole pass rather than hammering on: the limiter stays angry for a while,
    and the next scheduled run is only an hour away. Losing one cycle is cheap; losing the source
    is not.

    But "stop the pass" plus a fixed order means the tail of the list never runs at all, which is
    what happened — see `_next_start`. The pass therefore begins at whichever query has waited
    longest, so stopping early costs a different query each time instead of the same three."""
    out: dict = {"events": 0, "clusters": 0, "queries": 0, "rate_limited": False}
    remaining, why = _in_backoff(conn)
    if remaining > 0:
        out["skipped"] = f"backing off for another {remaining:.1f}h — {why}"
        log.info("gdelt: %s", out["skipped"])
        return out
    # Rotate which query goes first, so a pass that dies early does not always kill the same tail.
    ordered = list(queries or QUERIES)
    start = _next_start(conn, ordered)
    ordered = ordered[start:] + ordered[:start]
    out["started_with"] = ordered[0][0]
    with httpx.Client(timeout=45.0, headers=UA, follow_redirects=True) as client:
        for category, query in ordered:
            t0 = time.monotonic()
            try:
                articles = _fetch(client, query, timespan, maxrecords)
            except RateLimited:
                # Recorded as 429 whichever status carried it, so `_in_backoff` can see it.
                _record_call(conn, 429, int((time.monotonic() - t0) * 1000), False, category)
                log.warning("gdelt refused on volume at '%s'; stopping this pass", category)
                out["rate_limited"] = True
                break
            except httpx.HTTPStatusError as exc:
                ms = int((time.monotonic() - t0) * 1000)
                _record_call(conn, exc.response.status_code, ms, False, category)
                log.warning("gdelt %s failed for '%s'", exc.response.status_code, category)
                continue
            except Exception as exc:
                _record_call(conn, 0, int((time.monotonic() - t0) * 1000), False, category)
                log.warning("gdelt fetch failed for '%s' (%s)", category, type(exc).__name__)
                continue
            _record_call(conn, 200, int((time.monotonic() - t0) * 1000), True, category)
            out["queries"] += 1
            events = [e for e in (to_event(a, category) for a in articles) if e]
            res = spine.ingest_events(conn, events)
            out["events"] += res["events"]
            out["clusters"] += res["clusters"]
    return out
