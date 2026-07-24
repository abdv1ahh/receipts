"""Forward market calendar via Nasdaq's public JSON (Event & Macro Intelligence, Milestone 4).

Two "what's coming" feeds, keyless and reachable: upcoming EARNINGS (per company, with the consensus EPS
and pre/after-market timing) and upcoming US MACRO releases (FOMC, CPI, jobs, GDP, PCE, ...). We ingest
earnings only for names we already track (so each connects to the signal + attention planes) and keep
macro events only when they are US and actually market-moving — the rest is dropped, not shown as noise.
Nasdaq fingerprints non-browser clients, so a browser UA is required; the host is allowlisted (SSRF).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlparse

import httpx
from psycopg.types.json import Json

from .common import update_health

log = logging.getLogger("tradeos.calendar.nasdaq")

HOST = "api.nasdaq.com"
EARNINGS_URL = "https://api.nasdaq.com/api/calendar/earnings"
ECON_URL = "https://api.nasdaq.com/api/calendar/economicevents"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept": "application/json", "Accept-Language": "en-US,en;q=0.9",
}

# US macro releases that actually move markets -> (kind, importance). Matched as eventName substrings.
HIGH_IMPACT = {
    "fomc": ("fomc", "fed interest rate", "federal funds", "interest rate decision"),
    "cpi": ("consumer price index", "inflation rate", "cpi"),
    "jobs": ("non-farm payroll", "nonfarm payroll", "unemployment rate", "initial jobless"),
    "gdp": ("gdp",),
    "pce": ("pce", "personal consumption"),
    "retail": ("retail sales",),
    "ppi": ("producer price",),
}
_MED_HINT = ("michigan", "consumer confidence", "ism", "pmi", "durable goods", "housing starts", "adp")


# ------------------------------------------------------------------ pure classification

def classify_macro(country: str | None, event_name: str | None) -> tuple[str, str] | None:
    """(kind, importance) for a US market-moving macro event, or None to drop it. Pure + testable."""
    if (country or "").strip().lower() not in ("united states", "usa", "us"):
        return None
    n = (event_name or "").lower()
    for kind, needles in HIGH_IMPACT.items():
        if any(x in n for x in needles):
            return kind, "high"
    if any(x in n for x in _MED_HINT):
        return "macro", "medium"
    return None                                  # US but not a mover -> keep the calendar clean


def parse_earnings_time(t: str | None) -> str | None:
    t = (t or "").lower()
    if "pre-market" in t or "pre market" in t or "bmo" in t:
        return "pre-market"
    if "after" in t or "post" in t or "amc" in t:
        return "after-hours"
    return None


def cap_importance(market_cap: str | None) -> str:
    """Deterministic earnings importance from market cap ($50B+ high, $5B+ medium, else low)."""
    try:
        v = float((market_cap or "").replace("$", "").replace(",", "").strip())
    except ValueError:
        return "medium"
    if v >= 50e9:
        return "high"
    if v >= 5e9:
        return "medium"
    return "low"


# ------------------------------------------------------------------ ingest

def _tickered(conn) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute("SELECT symbol, entity_id FROM security_map WHERE source='sec_company_tickers'")
        out: dict[str, int] = {}
        for sym, eid in cur.fetchall():
            out.setdefault(sym, eid)
        return out


def _get(client, url, params):
    if urlparse(url).hostname != HOST:
        raise ValueError("nasdaq host allowlist violation")
    r = client.get(url, params=params)
    r.raise_for_status()
    return r.json()


def _store(conn, **e) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO market_events (kind, scope, title, event_date, event_time, importance,
                   symbol, entity_id, country, source, external_id, meta)
               VALUES (%(kind)s,%(scope)s,%(title)s,%(event_date)s,%(event_time)s,%(importance)s,
                   %(symbol)s,%(entity_id)s,%(country)s,%(source)s,%(external_id)s,%(meta)s)
               ON CONFLICT (source, external_id) DO UPDATE SET
                   event_date=EXCLUDED.event_date, event_time=EXCLUDED.event_time,
                   importance=EXCLUDED.importance, title=EXCLUDED.title, meta=EXCLUDED.meta""",
            {**e, "meta": Json(e["meta"])})
    conn.commit()


def _health(conn, source, n) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT max(event_date) FROM market_events WHERE source=%s", (source,))
        freshest = cur.fetchone()[0]
    ts = datetime.combine(freshest, datetime.min.time(), tzinfo=timezone.utc) if freshest else None
    update_health(conn, source, n, 0, ts)


def ingest_earnings(conn, days_ahead: int = 14) -> dict:
    """Upcoming earnings for tracked, tickered names over the next `days_ahead` business days."""
    counters = {"events": 0}
    known = _tickered(conn)
    today = date.today()
    with httpx.Client(timeout=25.0, headers=HEADERS, follow_redirects=True) as client:
        for i in range(days_ahead):
            d = today + timedelta(days=i)
            if d.weekday() >= 5:
                continue
            try:
                rows = ((_get(client, EARNINGS_URL, {"date": d.isoformat()}).get("data") or {}).get("rows")) or []
            except Exception as exc:
                log.warning("nasdaq earnings %s failed (%s)", d, type(exc).__name__)
                continue
            for row in rows:
                sym = (row.get("symbol") or "").strip().upper()
                if not sym or sym not in known:
                    continue
                _store(conn, kind="earnings", scope="company",
                       title=f"{row.get('name') or sym} earnings", event_date=d,
                       event_time=parse_earnings_time(row.get("time")),
                       importance=cap_importance(row.get("marketCap")), symbol=sym,
                       entity_id=known.get(sym), country="United States",
                       source="nasdaq/earnings", external_id=f"{sym}:{d.isoformat()}",
                       meta={"eps_forecast": row.get("epsForecast"), "fiscal_quarter": row.get("fiscalQuarterEnding"),
                             "market_cap": row.get("marketCap"), "num_estimates": row.get("noOfEsts"),
                             "last_year_eps": row.get("lastYearEPS")})
                counters["events"] += 1
    _health(conn, "nasdaq/earnings", counters["events"])
    return counters


def ingest_economic(conn, days_ahead: int = 10) -> dict:
    """Upcoming US market-moving macro releases over the next `days_ahead` days."""
    counters = {"events": 0}
    today = date.today()
    with httpx.Client(timeout=25.0, headers=HEADERS, follow_redirects=True) as client:
        for i in range(days_ahead):
            d = today + timedelta(days=i)
            try:
                rows = ((_get(client, ECON_URL, {"date": d.isoformat()}).get("data") or {}).get("rows")) or []
            except Exception as exc:
                log.warning("nasdaq econ %s failed (%s)", d, type(exc).__name__)
                continue
            for row in rows:
                cls = classify_macro(row.get("country"), row.get("eventName"))
                if not cls:
                    continue
                kind, importance = cls
                name = row.get("eventName")
                _store(conn, kind=kind, scope="macro", title=name, event_date=d, event_time=None,
                       importance=importance, symbol=None, entity_id=None, country=row.get("country"),
                       source="nasdaq/economic", external_id=f"{name}:{d.isoformat()}",
                       meta={"consensus": row.get("consensus"), "previous": row.get("previous"),
                             "actual": row.get("actual")})
                counters["events"] += 1
    _health(conn, "nasdaq/economic", counters["events"])
    return counters


def sources_status() -> list[dict]:
    return [{"key": "nasdaq/earnings", "label": "Earnings calendar", "state": "connected"},
            {"key": "nasdaq/economic", "label": "US economic calendar", "state": "connected"}]
