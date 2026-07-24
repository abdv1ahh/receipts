"""Event & Macro Intelligence read/enrich layer (Milestone 4) — the "what's coming" plane.

Turns the raw forward calendar (market_events) into intelligence two ways:
  * MACRO events get a deterministic, educational read — what the release is and which sectors/assets it
    tends to move. A curated knowledge base, not a model's opinion and never advice.
  * COMPANY (earnings) events get CROSS-PLANE enrichment: is this name ALSO showing a smart-money signal
    or an unusual attention spike? An earnings print on a name smart money is buying, or that the crowd
    is suddenly watching, is the kind of setup a trader wants flagged before the day arrives.
"""
from __future__ import annotations

from datetime import date, timedelta

import psycopg

from . import news, sentiment

# Deterministic macro knowledge base: what the release is + which assets/sectors it typically moves.
# Educational and descriptive — it explains transmission channels, it never tells anyone what to do.
MACRO_INTEL = {
    "fomc": {"what": "The Federal Reserve's interest-rate decision.",
             "moves": "Rate-sensitive groups react most — banks, REITs, homebuilders, and long-duration growth/tech. The statement and the 'dot plot' often move markets more than the decision itself."},
    "cpi": {"what": "Consumer price inflation.",
            "moves": "A hot print pressures rates and long-duration tech/growth; a cool print tends to lift risk assets. Gold and the dollar move with real-rate expectations."},
    "jobs": {"what": "The labor market — payrolls, unemployment, or jobless claims.",
             "moves": "Shapes rate-cut odds. A strong report can lift yields (a headwind for growth) but signals demand; a weak one raises slowdown worry."},
    "gdp": {"what": "The pace of economic growth.",
            "moves": "Broad risk sentiment and cyclicals — industrials, materials, and consumer discretionary."},
    "pce": {"what": "The Fed's preferred inflation gauge.",
            "moves": "Same channels as CPI, watched especially closely heading into an FOMC meeting."},
    "retail": {"what": "Consumer spending.",
               "moves": "Consumer-discretionary, retail, and payments names most directly."},
    "ppi": {"what": "Producer (wholesale) inflation.",
            "moves": "A leading tell for consumer inflation; rates and margin-sensitive sectors watch it."},
    "macro": {"what": "A scheduled US economic release.",
              "moves": "Watched for its read on growth and inflation, which set the tone for rates and risk."},
}


def _attention_map(conn, hours: int = 96) -> dict:
    return {r["symbol"]: r for r in sentiment.trending_board(conn, hours=hours, min_mentions=3, limit=250)}


def _enrich(ev: dict, sig: set, attn: dict) -> dict:
    if ev["scope"] == "macro":
        intel = MACRO_INTEL.get(ev["kind"], MACRO_INTEL["macro"])
        ev["what"], ev["moves"] = intel["what"], intel["moves"]
    else:
        flags = []
        if ev["symbol"] in sig:
            flags.append("smart_money")
        a = attn.get(ev["symbol"])
        if a and (a.get("velocity") or 0) >= 1.3:
            flags.append("attention")
            ev["attention_velocity"] = a.get("velocity")
        ev["cross_plane"] = flags
    return ev


def upcoming(conn: psycopg.Connection, days: int = 10) -> list[dict]:
    """Enriched forward calendar for the next `days` days, ordered by date then importance."""
    sig = news.signal_symbols(conn)
    attn = _attention_map(conn)
    today = date.today()
    with conn.cursor() as cur:
        cur.execute(
            """SELECT id, kind, scope, title, event_date, event_time, importance, symbol, country, meta
               FROM market_events WHERE event_date >= %s AND event_date <= %s
               ORDER BY event_date,
                        CASE importance WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, symbol""",
            (today, today + timedelta(days=days)))
        rows = cur.fetchall()
    out = []
    for (eid, kind, scope, title, edate, etime, imp, symbol, country, meta) in rows:
        out.append(_enrich({"id": eid, "kind": kind, "scope": scope, "title": title,
                            "date": edate.isoformat(), "time": etime, "importance": imp,
                            "symbol": symbol, "country": country, "meta": meta or {}}, sig, attn))
    return out


def by_day(conn: psycopg.Connection, days: int = 10) -> list[dict]:
    grouped: dict[str, list] = {}
    for e in upcoming(conn, days):
        grouped.setdefault(e["date"], []).append(e)
    return [{"date": d, "events": grouped[d]} for d in sorted(grouped)]


def _notability(e: dict) -> int:
    s = {"high": 3, "medium": 2}.get(e["importance"], 1)
    s += 2 * len(e.get("cross_plane", []))     # earnings on a signal/attention name jumps the queue
    return s


def brief_events(conn: psycopg.Connection, days: int = 7, limit: int = 6) -> list[dict]:
    """The most notable upcoming events for the Morning Brief: high-impact macro + earnings that overlap
    a smart-money signal or an attention spike, soonest first among equals."""
    evs = upcoming(conn, days)
    evs.sort(key=lambda e: (-_notability(e), e["date"]))
    return evs[:limit]
