"""Read-only tools the assistant can call, instead of a bigger system prompt.

The brief is specific about this: "Give it tools rather than making it a chat box with a system
prompt. It queries the event store, the claim store, and the Ledger... and cites specific stored
events with links in every answer. It must be able to say it does not know, and must never invent
a data point that is not in the store. Asked about its own reliability, it reads the Ledger and
answers honestly."

Three security properties hold by construction, because Phase 2 made this application ingest
arbitrary internet text and the model that reads it is the same one calling these tools:

  **Read-only.** There is no write tool and no way to add one by accident — the registry maps a
  name to a function, and every function opens a cursor for SELECT only. Nothing here takes a
  table name, a column name, or a fragment of SQL.

  **Parameterised, always.** A tool takes typed arguments that become bound parameters. The model
  never composes a query; it picks a tool and fills in blanks that are clamped and validated here.

  **No URL fetching.** No tool takes a URL or reaches the network. An injected instruction telling
  the assistant to "fetch this address" has nothing to call.

Every tool returns rows that already carry their own provenance — a source, a timestamp, a link —
so an answer can cite what it used without the model having to remember it.
"""
from __future__ import annotations

import logging

log = logging.getLogger("tradeos.assistant_tools")

MAX_ROWS = 12                  # bounds every result set; an answer citing 200 rows cites nothing


def _clamp(value, low, high, default):
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return default


def search_events(conn, query: str = "", days: int = 14, limit: int = 8) -> dict:
    """Recent events whose title matches a phrase. Trigram similarity, so a near-miss still finds
    it — the same matching the spine uses to cluster."""
    days, limit = _clamp(days, 1, 90, 14), _clamp(limit, 1, MAX_ROWS, 8)
    q = (query or "").strip()[:200]
    with conn.cursor() as cur:
        if q:
            cur.execute(
                """SELECT id, title, source, source_url, knowable_time, category, geo
                     FROM events
                    WHERE knowable_time >= now() - make_interval(days => %s)
                      AND (title ILIKE %s OR similarity(title, %s) > 0.25)
                 ORDER BY similarity(title, %s) DESC, knowable_time DESC
                    LIMIT %s""", (days, f"%{q}%", q, q, limit))
        else:
            cur.execute(
                """SELECT id, title, source, source_url, knowable_time, category, geo
                     FROM events
                    WHERE knowable_time >= now() - make_interval(days => %s)
                 ORDER BY knowable_time DESC LIMIT %s""", (days, limit))
        cols = ("id", "title", "source", "url", "knowable_time", "category", "geo")
        rows = [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]
    for r in rows:
        r["knowable_time"] = r["knowable_time"].isoformat()
    return {"events": rows, "found": len(rows)}


def search_claims(conn, subject: str = "", days: int = 21, limit: int = 8) -> dict:
    """Live interpretations, optionally about one asset/sector/currency."""
    days, limit = _clamp(days, 1, 90, 21), _clamp(limit, 1, MAX_ROWS, 8)
    subj = (subject or "").strip().upper()[:64]
    with conn.cursor() as cur:
        cur.execute(
            """SELECT c.id, c.mechanism, c.affected, c.confidence, c.horizon, c.status,
                      c.created_at, c.contradicts, e.title, e.source_url
                 FROM claims c LEFT JOIN events e ON e.id = c.event_id
                WHERE c.created_at >= now() - make_interval(days => %s)
                  AND (%s = '' OR EXISTS (SELECT 1 FROM jsonb_array_elements(c.affected) a
                                           WHERE upper(a->>'value') = %s))
             ORDER BY c.confidence DESC, c.created_at DESC
                LIMIT %s""", (days, subj, subj, limit))
        cols = ("id", "mechanism", "affected", "confidence", "horizon", "status", "created_at",
                "contradicts", "headline", "url")
        rows = [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]
    for r in rows:
        r["created_at"] = r["created_at"].isoformat()
        r["disagreements"] = len(r.pop("contradicts") or [])
    return {"claims": rows, "found": len(rows)}


def track_record(conn) -> dict:
    """The Ledger. This is the tool that answers "how often are you right?" — and it is the reason
    the assistant can answer that honestly instead of guessing at its own reliability."""
    from . import ledger
    summary = ledger.summary(conn)
    return {"overall": summary["overall"], "by_category": summary["by"].get("category", []),
            "by_horizon": summary["by"].get("horizon", []),
            "calibration": summary["calibration"],
            "recent_misses": ledger.recent_misses(conn, limit=5),
            "caveat": summary["note"]}


def country_exposure(conn, country: str = "") -> dict:
    """A country's currency regime, index, trade partners and commodity position."""
    iso = (country or "").strip().upper()[:2]
    with conn.cursor() as cur:
        cur.execute("""SELECT country, name, currency, currency_regime, pegged_to, main_index,
                              export_partners, import_partners, key_exports, key_imports,
                              commodity_exposure, source
                         FROM country_exposure WHERE country = %s""", (iso,))
        row = cur.fetchone()
    if not row:
        with conn.cursor() as cur:
            cur.execute("SELECT country, name FROM country_exposure ORDER BY name")
            available = [{"country": c, "name": n} for c, n in cur.fetchall()]
        return {"found": False,
                "note": f"No exposure data for {iso or 'that country'} yet.",
                "available": available}
    cols = ("country", "name", "currency", "currency_regime", "pegged_to", "main_index",
            "export_partners", "import_partners", "key_exports", "key_imports",
            "commodity_exposure", "source")
    return {"found": True, **dict(zip(cols, row, strict=True))}


def smart_money(conn, symbol: str = "", limit: int = 6) -> dict:
    """Current SEC-derived convergence signals, with the reporting lag stated.

    The 13F lag is included in every response on purpose. An institutional holding can be up to 45
    days stale by the time it is public, and an answer that omits that is misleading even when
    every number in it is correct."""
    limit = _clamp(limit, 1, MAX_ROWS, 6)
    sym = (symbol or "").strip().upper()[:12]
    with conn.cursor() as cur:
        cur.execute(
            """SELECT m.symbol, e.name, c.score, c.confidence_bucket, c.as_of
                 FROM signal_clusters c
                 JOIN entities e ON e.id = c.issuer_entity
                 LEFT JOIN security_map m ON m.entity_id = c.issuer_entity
                                         AND m.source = 'sec_company_tickers'
                WHERE c.as_of = (SELECT max(as_of) FROM signal_clusters)
                  AND (%s = '' OR m.symbol = %s)
             ORDER BY c.score DESC LIMIT %s""", (sym, sym, limit))
        cols = ("symbol", "name", "score", "confidence_bucket", "as_of")
        rows = [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]
    for r in rows:
        r["as_of"] = r["as_of"].isoformat() if r["as_of"] else None
        r["score"] = float(r["score"])
    return {"signals": rows, "found": len(rows),
            "reporting_lag": ("13F institutional holdings are disclosed up to 45 days after the "
                              "quarter ends, so a position shown here may already have changed. "
                              "Form 4 insider transactions are far fresher, typically two business "
                              "days.")}


def data_coverage(conn) -> dict:
    """What this product can and cannot currently see. The tool that lets the assistant say "I
    don't know" with a reason rather than guessing."""
    from . import sources
    rows = sources.health(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM events")
        events = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM claims")
        claims = cur.fetchone()[0]
    return {
        "events_stored": events, "claims_made": claims,
        "connected": [r["label"] for r in rows if r["state"] == sources.CONNECTED],
        "needs_key": [r["label"] for r in rows if r["state"] == sources.NEEDS_KEY],
        "unavailable": [r["label"] for r in rows if r["state"] == sources.UNAVAILABLE],
    }


# name -> (function, one-line description the model sees). Adding a tool means adding a READ
# function here; there is deliberately no generic "run this query" escape hatch.
TOOLS: dict[str, tuple] = {
    "search_events": (search_events,
                      "Find recent world events by phrase. Args: query, days, limit."),
    "search_claims": (search_claims,
                      "Find live interpretations, optionally about one asset/sector/currency. "
                      "Args: subject, days, limit."),
    "track_record": (track_record,
                     "This system's own accuracy record, including its misses. No args."),
    "country_exposure": (country_exposure,
                         "A country's currency regime, index, trade partners and commodities. "
                         "Args: country (ISO alpha-2)."),
    "smart_money": (smart_money,
                    "Current SEC-derived convergence signals and the reporting lag. "
                    "Args: symbol, limit."),
    "data_coverage": (data_coverage,
                      "What this product can and cannot currently see. No args."),
}


def describe() -> str:
    """The tool list as the model sees it."""
    return "\n".join(f"  {name}: {desc}" for name, (_fn, desc) in TOOLS.items())


def call(conn, name: str, args: dict | None = None) -> dict:
    """Invoke one tool by name. Unknown names are refused rather than guessed at, and a tool that
    raises returns an error rather than propagating — the assistant must be able to say a lookup
    failed without the whole answer failing."""
    entry = TOOLS.get(name)
    if not entry:
        return {"error": f"no such tool: {name}", "available": sorted(TOOLS)}
    fn = entry[0]
    safe = {k: v for k, v in (args or {}).items()
            if k in fn.__code__.co_varnames[:fn.__code__.co_argcount] and k != "conn"}
    try:
        return fn(conn, **safe)
    except Exception as exc:
        log.warning("assistant tool %s failed (%s)", name, type(exc).__name__)
        return {"error": f"the {name} lookup failed"}
