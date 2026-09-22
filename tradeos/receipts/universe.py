"""Which symbols a call may be published on, and nothing else.

This module is a DOOR, and it exists because of what Part A established. After the benchmark-gap
fixes there is exactly one remaining way for a call to be sealed with a permanent `unscoreable`
verdict: we hold no price series for its symbol at all. Every other gap leaves the call open and
recoverable. So closing that one case at the point of ENTRY closes it completely — a caller who
cannot type an unpriceable symbol cannot receive an uncorrectable verdict on one.

It was not a theoretical risk. The publish form's own placeholder read `AAPL`, and measured
2026-09-15 this database holds **zero** price rows for AAPL: a caller following the form's example
would have sealed a permanent unscoreable on their first call. The universe is 2,018 symbols and
none of the names a person reaches for first are necessarily in it, which is exactly why it has to
be offered rather than guessed at.

WHY THE WHOLE LIST IS CACHED IN PROCESS rather than queried per keystroke. `prices_eod` has a
primary key on (symbol, day) and 2.2M rows, so there is no index that answers "distinct symbols"
without scanning: a prefix query measured 35ms and a bare `A%` 39ms, on every keystroke. Rolling up
ALL 2,018 symbols with their last close measured **58ms once**, and the answer only changes when
`ingest_prices` runs — every six hours. So one query per TTL and prefix matching over 2,018 strings
in Python, which is free. Same shape as `flags`: a short TTL bounds how stale a toggle can be.
"""
from __future__ import annotations

import threading
import time
from datetime import date

import psycopg

# Bounds how long a newly-ingested symbol can be missing from the suggestions. Generous, because
# the underlying data moves once a day at most.
_TTL = 60.0

# How far behind the benchmark a symbol may sit and still be offered. A stale symbol IS publishable
# — it publishes open and is scored when the feed catches up — so it stays in the list and is
# labelled rather than hidden. Hiding it would be the wrong lesson from Part A: the case that had
# to be closed was "no series at all", not "series a few days behind".
STALE_DAYS = 5

_lock = threading.Lock()
_cache: tuple[float, list[dict]] | None = None


def _load(conn: psycopg.Connection, benchmark: str) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute("SELECT max(day) FROM prices_eod WHERE symbol = %s", (benchmark,))
        row = cur.fetchone()
        bench_last: date | None = row[0] if row else None
        cur.execute("SELECT symbol, max(day) FROM prices_eod GROUP BY symbol ORDER BY symbol")
        rows = cur.fetchall()
    out = []
    for symbol, last in rows:
        behind = (bench_last - last).days if (bench_last and last) else 0
        out.append({"symbol": symbol, "last_session": last.isoformat() if last else None,
                    "days_behind": max(0, behind), "fresh": behind <= STALE_DAYS})
    return out


def scoreable_symbols(conn: psycopg.Connection, benchmark: str = "SPY",
                      now: float | None = None) -> list[dict]:
    """Every symbol we hold a price series for, with how current it is. Cached for `_TTL`."""
    global _cache
    now = now if now is not None else time.monotonic()
    with _lock:
        if _cache and now - _cache[0] < _TTL:
            return _cache[1]
    loaded = _load(conn, benchmark)
    with _lock:
        _cache = (now, loaded)
    return loaded


def reset_cache() -> None:
    """Drop the cached universe. For tests and for an operator who has just backfilled."""
    global _cache
    with _lock:
        _cache = None


def match(universe: list[dict], query: str, limit: int = 8) -> list[dict]:
    """Prefix matches for a part-typed ticker, best first. Pure.

    Ordering, which is the whole usefulness of an autocomplete: an EXACT match first, because
    someone who has typed the whole symbol has already chosen; then shortest first, because a
    ticker is a name and `AAP` is a more likely intent than `AAPXYZ` for someone who typed `AAP`;
    then alphabetical so the list is stable between keystrokes. Freshness deliberately does NOT
    reorder anything — a caller looking for a specific symbol should find it where they expect it,
    with its staleness shown, rather than have it pushed down a list for a reason they cannot see.
    """
    q = (query or "").strip().upper()
    if not q:
        return []
    hits = [s for s in universe if s["symbol"].startswith(q)]
    hits.sort(key=lambda s: (s["symbol"] != q, len(s["symbol"]), s["symbol"]))
    return hits[:limit]


def holds(universe: list[dict], symbol: str) -> bool:
    """Whether a call on this exact symbol could ever be scored. Pure."""
    return any(s["symbol"] == (symbol or "").strip().upper() for s in universe)


def suggest(conn: psycopg.Connection, query: str, limit: int = 8,
            benchmark: str = "SPY") -> dict:
    """What the publish form shows under a part-typed ticker."""
    universe = scoreable_symbols(conn, benchmark)
    matches = match(universe, query, limit)
    return {"query": (query or "").strip().upper(), "matches": matches,
            "universe_size": len(universe),
            # Said explicitly rather than implied by an empty list. "We hold prices for 2,018
            # symbols and none of them start with that" is actionable; a blank dropdown is not.
            "note": (f"No symbol we hold prices for starts with "
                     f"{(query or '').strip().upper()!r}. We hold {len(universe)} symbols, and a "
                     f"call can only be published on one of them — otherwise it could never be "
                     f"scored." if query and not matches else None)}
