"""Market & macro news via public RSS/Atom feeds (News Intelligence, Milestone 1).

Where the 8-K source gives precise, ticker-linked corporate events, this gives the broader "what is
moving markets" context the Morning Brief needs: monetary policy, macro releases, and top market
headlines. Honesty rules, held deliberately tight:

  - Allowlisted hosts only, HTTPS only (SSRF discipline, mirrors edgar_client). Each feed's connected/
    degraded state is surfaced, never hidden (news.sources_status()).
  - We store a headline, a short source-provided summary, the link, the source, and the time — we do
    NOT republish article bodies.
  - Ticker tagging is HIGH-PRECISION ONLY: an explicit $CASHTAG, an exchange-qualified mention like
    "(NASDAQ: AAPL)", or an exact mega-cap name. Anything ambiguous stays untagged market news rather
    than risk a fabricated association — the same "never guess a fact" line the filings pipeline holds.
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import httpx
from defusedxml.ElementTree import fromstring
from psycopg.types.json import Json

from .common import update_health

log = logging.getLogger("tradeos.ingest.news_rss")


@dataclass(frozen=True)
class Feed:
    key: str          # -> source = 'rss/<key>'
    url: str
    label: str
    category: str     # default category for items from this feed


# Curated allowlist. Weighted toward official / public-domain feeds (the safest, highest-signal macro
# sources) plus a couple of broad market headline feeds. Extend here; the host allowlist derives from it.
FEEDS: list[Feed] = [
    Feed("fed", "https://www.federalreserve.gov/feeds/press_all.xml", "Federal Reserve", "macro"),
    Feed("sec", "https://www.sec.gov/news/pressreleases.rss", "SEC Press", "regulatory"),
    Feed("cnbc-markets", "https://www.cnbc.com/id/20910258/device/rss/rss.html", "CNBC Markets", "markets"),
    Feed("cnbc-top", "https://www.cnbc.com/id/100003114/device/rss/rss.html", "CNBC Top News", "markets"),
]
# NOTE: feed curation is deliberate — noisy personal-finance feeds were dropped so the brief leads
# with market-moving news, not lifestyle columns. Extend with vetted, market-focused feeds only.
_ALLOWED_HOSTS = {urlparse(f.url).hostname for f in FEEDS}

# High-precision mega-cap name → ticker map for tagging plain-language headlines ("Nvidia", "Apple").
# Deliberately small and unambiguous; ambiguous or generic names are omitted (left untagged).
MEGACAP_NAMES: dict[str, str] = {
    "nvidia": "NVDA", "apple": "AAPL", "microsoft": "MSFT", "amazon": "AMZN", "alphabet": "GOOGL",
    "google": "GOOGL", "meta platforms": "META", "tesla": "TSLA", "broadcom": "AVGO", "netflix": "NFLX",
    "jpmorgan": "JPM", "goldman sachs": "GS", "berkshire hathaway": "BRK.B", "eli lilly": "LLY",
    "exxon mobil": "XOM", "walmart": "WMT", "coca-cola": "KO", "boeing": "BA", "palantir": "PLTR",
    "advanced micro devices": "AMD", "micron": "MU", "intel": "INTC", "oracle": "ORCL", "salesforce": "CRM",
    "pfizer": "PFE", "moderna": "MRNA", "starbucks": "SBUX", "nike": "NKE", "disney": "DIS",
    "coinbase": "COIN", "robinhood": "HOOD", "uber": "UBER", "ford": "F", "general motors": "GM",
}
_CASHTAG = re.compile(r"\$([A-Z]{1,5}(?:\.[A-Z])?)\b")
_EXCHANGE_QUAL = re.compile(r"\((?:NYSE|NASDAQ|NYSEARCA|AMEX|OTC)[:\s]+([A-Z]{1,5}(?:\.[A-Z])?)\)", re.I)

# Corporate-name normalization for higher-recall (still precise) tagging off the tracked universe.
_SUFFIX = re.compile(r"\b(corporation|corp|incorporated|inc|company|co|ltd|limited|plc|holdings|"
                     r"group|the|class\s+[a-c]|/[a-z]{2}/)\b", re.I)
# Normalized names too generic to tag safely (common words / ambiguous across many issuers).
_AMBIGUOUS = {"first", "national", "american", "united", "global", "general", "capital", "financial",
              "energy", "technology", "industries", "systems", "solutions", "international", "pacific",
              "atlantic", "central", "northern", "southern", "eastern", "western", "new", "old"}


def _normalize_name(name: str) -> str:
    n = re.sub(r"[.,/&]", " ", (name or "").lower())
    n = _SUFFIX.sub(" ", n)
    return re.sub(r"\s+", " ", n).strip()


class RssClient:
    """Throttle-light allowlisted fetcher for the feed hosts only."""

    def __init__(self, user_agent: str = "TradeOSS-news/1.0"):
        self._client = httpx.Client(headers={"User-Agent": user_agent}, timeout=30.0, follow_redirects=True)

    def get(self, url: str) -> bytes:
        p = urlparse(url)
        if p.scheme != "https":
            raise ValueError(f"refusing non-https feed: {url}")
        if p.hostname not in _ALLOWED_HOSTS:
            raise ValueError(f"refusing host outside feed allowlist: {p.hostname}")
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.content

    def close(self) -> None:
        self._client.close()


# ------------------------------------------------------------------ pure: feed parsing + tagging

def _strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _text(el) -> str:
    return (el.text or "").strip() if el is not None else ""


def _parse_when(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)              # RFC-822 (RSS pubDate)
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))  # ISO-8601 (Atom)
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class RawEntry:
    external_id: str
    url: str
    title: str
    summary: str
    published_at: datetime | None


def parse_feed(xml: bytes) -> list[RawEntry]:
    """Tolerant RSS-2.0 + Atom parser (namespace-agnostic). Pure + offline-testable."""
    root = fromstring(xml)
    entries: list[RawEntry] = []
    # RSS: root/channel/item ; Atom: root/entry
    nodes = [e for e in root.iter() if _strip_ns(e.tag) in ("item", "entry")]
    for node in nodes:
        title = link = summary = guid = published = ""
        for child in node:
            t = _strip_ns(child.tag)
            if t == "title":
                title = _text(child)
            elif t == "link":
                link = _text(child) or child.attrib.get("href", "")   # Atom uses href attr
            elif t in ("description", "summary"):
                summary = _text(child)
            elif t in ("guid", "id"):
                guid = _text(child)
            elif t in ("pubdate", "published", "updated", "date"):
                published = published or _text(child)
        title = re.sub(r"<[^>]+>", "", title).strip()
        summary = re.sub(r"<[^>]+>", "", summary).strip()
        if not title or not link:
            continue
        ext = guid or link
        entries.append(RawEntry(ext, link, title, summary[:600], _parse_when(published)))
    return entries


def tag_symbols(text: str, known: set[str], name_index: dict[str, str] | None = None) -> list[str]:
    """High-precision tickers mentioned in a headline/summary. Only unambiguous signals count, and
    every hit must exist in our security universe (`known`). `name_index` (normalized_name -> symbol,
    built from the tracked universe) raises recall while staying word-boundary exact."""
    found: list[str] = []
    for m in _CASHTAG.finditer(text):
        found.append(m.group(1).upper())
    for m in _EXCHANGE_QUAL.finditer(text):
        found.append(m.group(1).upper())
    low = text.lower()
    for name, sym in MEGACAP_NAMES.items():
        if name in low and re.search(rf"\b{re.escape(name)}\b", low):
            found.append(sym)
    for norm, sym in (name_index or {}).items():
        if norm in low and re.search(rf"\b{re.escape(norm)}\b", low):   # fast substring gate, then exact
            found.append(sym)
    out, seen = [], set()
    for s in found:
        if s in known and s not in seen:
            seen.add(s)
            out.append(s)
    return out


# ------------------------------------------------------------------ DB ingest

def _known_symbols(conn) -> set[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT symbol FROM security_map WHERE source='sec_company_tickers'")
        return {r[0] for r in cur.fetchall()}


def _name_index(conn) -> dict[str, str]:
    """{normalized_company_name: symbol} across the tracked universe, gated to names specific enough
    to tag safely (>= 5 chars, not in the ambiguity stoplist). First writer wins on collisions."""
    idx: dict[str, str] = {}
    with conn.cursor() as cur:
        cur.execute(
            """SELECT e.name, (SELECT symbol FROM security_map m WHERE m.entity_id=e.id
                                 AND m.source='sec_company_tickers' ORDER BY confidence DESC LIMIT 1)
               FROM entities e WHERE e.cik IS NOT NULL""")
        for name, sym in cur.fetchall():
            if not sym:
                continue
            norm = _normalize_name(name)
            if len(norm) >= 5 and norm not in _AMBIGUOUS:
                idx.setdefault(norm, sym)
    return idx


def _entity_for(conn, symbol: str) -> int | None:
    with conn.cursor() as cur:
        cur.execute("SELECT entity_id FROM security_map WHERE symbol=%s AND source='sec_company_tickers' "
                    "ORDER BY confidence DESC LIMIT 1", (symbol,))
        r = cur.fetchone()
        return r[0] if r else None


def ingest(conn, client: RssClient, limit_per_feed: int = 40) -> dict:
    """Fetch every allowlisted feed, store new headlines, tag high-precision tickers. Idempotent
    (external_id per source). Degrades loudly per feed — one bad feed never sinks the run."""
    known = _known_symbols(conn)
    name_index = _name_index(conn)
    totals = {"items": 0, "tagged": 0, "feeds_ok": 0, "feeds_failed": 0}
    for feed in FEEDS:
        source = f"rss/{feed.key}"
        try:
            entries = parse_feed(client.get(feed.url))[:limit_per_feed]
        except Exception as exc:
            totals["feeds_failed"] += 1
            log.warning("feed %s failed (%s); skipping", feed.key, type(exc).__name__)
            continue
        added = 0
        for e in entries:
            ext = hashlib.sha256(e.external_id.encode()).hexdigest()[:32]
            knowable = e.published_at or datetime.now(timezone.utc)
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO news_items (source, external_id, url, headline, summary, category,
                                               published_at, knowable_time, meta)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (source, external_id) DO NOTHING RETURNING id""",
                    (source, ext, e.url, e.title, e.summary or None, feed.category,
                     e.published_at, knowable, Json({"feed": feed.label})))
                row = cur.fetchone()
                if row is None:
                    continue
                news_id = row[0]
                added += 1
                for sym in tag_symbols(f"{e.title} {e.summary}", known, name_index):
                    cur.execute(
                        """INSERT INTO news_item_entities (news_id, entity_id, symbol, relation)
                           VALUES (%s,%s,%s,'mentioned') ON CONFLICT (news_id, symbol) DO NOTHING""",
                        (news_id, _entity_for(conn, sym), sym))
                    totals["tagged"] += 1
            conn.commit()
        with conn.cursor() as cur:
            cur.execute("SELECT max(knowable_time) FROM news_items WHERE source=%s", (source,))
            freshest = cur.fetchone()[0]
        update_health(conn, source, added, 0, freshest)
        conn.commit()
        totals["items"] += added
        totals["feeds_ok"] += 1
        log.info("feed %s: +%d items", feed.key, added)
    return totals
