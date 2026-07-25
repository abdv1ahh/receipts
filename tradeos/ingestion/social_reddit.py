"""Reddit discussion source (Social & Attention Intelligence, Milestone 2).

The ToS-compliant path: a client_credentials OAuth app (oauth.reddit.com, reachable from a datacenter
IP — unlike the public .json scrape, which Reddit Cloudflare-blocks). It stays dark until the operator
adds a free Reddit app's REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET (config.reddit_configured()); until
then the source honestly reports 'needs_key' and NOTHING is fabricated.

Reddit is a discussion source, so unlike Wikipedia it carries sentiment — measured with a transparent
bull/bear lexicon (labelled a heuristic in meta, never presented as a precise reading). Ticker
extraction is conservative (cashtags + known-ticker tokens that aren't common English words), the same
'never guess an association' bar the rest of the pipeline holds.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx

from .. import config, sentiment

log = logging.getLogger("tradeos.social.reddit")

OAUTH_ENDPOINT = "https://www.reddit.com/api/v1/access_token"   # endpoint, not a secret
API = "https://oauth.reddit.com"
API_HOST = "oauth.reddit.com"
UA = "TradeOSS/1.0 (market-attention research)"
SUBREDDITS = ["wallstreetbets", "stocks", "investing", "options", "StockMarket"]

_CASHTAG = re.compile(r"\$([A-Za-z]{1,5})\b")
_TOKEN = re.compile(r"\b([A-Z]{2,5})\b")
# common all-caps words that collide with tickers — never tagged from a bare token (cashtag still counts)
_STOP = {"A", "I", "IT", "IS", "BE", "ON", "SO", "OR", "AT", "BY", "GO", "UP", "AN", "AM", "AS", "IF",
         "WE", "US", "TO", "DO", "NO", "OK", "ALL", "ANY", "ARE", "FOR", "NEW", "NOW", "CEO", "CFO",
         "IPO", "ATH", "YOLO", "FD", "FDS", "DD", "WSB", "EPS", "GDP", "CPI", "FED", "SEC", "ETF",
         "USA", "USD", "AI", "PR", "Q1", "Q2", "Q3", "Q4", "TA", "PT", "EOD", "AH", "IV", "OTM", "ITM"}

_BULL = {"call", "calls", "long", "buy", "bought", "bull", "bullish", "moon", "rocket", "squeeze",
         "breakout", "rip", "green", "up", "pump", "hold", "hodl", "diamond"}
_BEAR = {"put", "puts", "short", "sell", "sold", "bear", "bearish", "crash", "dump", "red", "down",
         "drill", "tank", "rug", "baghold", "drop", "collapse"}
_WORD = re.compile(r"[a-z']+")


# ------------------------------------------------------------------ pure: extraction + sentiment

def extract_symbols(text: str, known: set[str]) -> list[str]:
    """Tickers referenced in a post — cashtags always, bare CAPS tokens only if a known ticker and not
    a common word. Every hit must be in `known`. Deterministic + offline-testable."""
    out, seen = [], set()
    for m in _CASHTAG.finditer(text or ""):
        s = m.group(1).upper()
        if s in known and s not in seen:
            seen.add(s)
            out.append(s)
    for m in _TOKEN.finditer(text or ""):
        s = m.group(1)
        if s in known and s not in _STOP and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def lexicon_sentiment(text: str) -> float | None:
    """Transparent bull/bear score in [-1, 1] from a small lexicon, or None when neither side appears.
    A heuristic, labelled as such — not presented as a precise sentiment reading."""
    words = _WORD.findall((text or "").lower())
    b = sum(1 for w in words if w in _BULL)
    s = sum(1 for w in words if w in _BEAR)
    if b + s == 0:
        return None
    return round((b - s) / (b + s), 3)


# ------------------------------------------------------------------ OAuth + fetch

def _token(client: httpx.Client) -> str:
    cid, secret = config.reddit_client_id(), config.reddit_client_secret()
    r = client.post(OAUTH_ENDPOINT, data={"grant_type": "client_credentials"}, auth=(cid, secret),
                    headers={"User-Agent": UA})
    r.raise_for_status()
    return r.json()["access_token"]


def _posts(client: httpx.Client, token: str, sub: str, limit: int = 100) -> list[dict]:
    url = f"{API}/r/{sub}/hot"
    if urlparse(url).hostname != API_HOST:
        raise ValueError("reddit host allowlist violation")
    r = client.get(url, params={"limit": limit}, headers={"User-Agent": UA, "Authorization": f"bearer {token}"})
    r.raise_for_status()
    children = r.json().get("data", {}).get("children", [])
    return [c.get("data", {}) for c in children]


# ------------------------------------------------------------------ ingest

def ingest(conn, known: set[str] | None = None, subs: list[str] | None = None, limit: int = 100) -> int:
    """Tally ticker mentions + heuristic sentiment across finance subreddits, one observation per symbol.
    No-op (returns 0) when Reddit isn't configured — honest, never fabricated."""
    if not config.reddit_configured():
        log.info("reddit not configured; skipping (honest no-op)")
        return 0
    subs = subs or SUBREDDITS
    if known is None:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT symbol FROM security_map WHERE source='sec_company_tickers'")
            known = {r[0] for r in cur.fetchall()}
    now = datetime.now(UTC)
    agg: dict[str, dict] = {}
    with httpx.Client(timeout=25.0) as client:
        token = _token(client)
        for sub in subs:
            try:
                posts = _posts(client, token, sub, limit)
            except Exception as exc:
                log.warning("reddit fetch failed for r/%s (%s)", sub, type(exc).__name__)
                continue
            for p in posts:
                text = f"{p.get('title','')} {p.get('selftext','')}"
                sent = lexicon_sentiment(text)
                for sym in extract_symbols(text, known):
                    a = agg.setdefault(sym, {"mentions": 0, "sent_sum": 0.0, "sent_n": 0})
                    a["mentions"] += 1
                    if sent is not None:
                        a["sent_sum"] += sent
                        a["sent_n"] += 1
            time.sleep(0.5)   # be polite to the API
    written = 0
    for sym, a in agg.items():
        sent = round(a["sent_sum"] / a["sent_n"], 3) if a["sent_n"] else None
        sentiment.record_observation(conn, "reddit", sym, None, now, 24, a["mentions"],
                                     baseline=None, sentiment=sent,
                                     meta={"sentiment_method": "lexicon_heuristic", "subs": subs})
        written += 1
    return written
