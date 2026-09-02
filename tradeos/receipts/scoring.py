"""Resolving a call against what actually happened.

The arithmetic is deliberately boring and deliberately borrowed. `backtest.engine.excess_return` is
the one implementation of "how did this move against SPY over this window" in the codebase, and
`ledger.verdict_for` is the one implementation of "does that count as a hit". Both are reused here
rather than reimplemented, because a scoring rule that exists twice is a scoring rule that will
eventually disagree with itself, and the whole product is a claim that this number can be trusted.

Two conventions do the real work, and both exist to stop a record flattering its owner:

  ENTRY IS THE NEXT SESSION.   Never the session in progress. A call published at 3pm cannot enter
                               at that day's close, because by 3pm most of that close has already
                               happened. `entry_day_after` takes the first session STRICTLY after
                               publication.

  THE NOISE FLOOR IS REAL.     A call that said up and got +0.4% against SPY did not predict
                               anything; it landed inside the noise. Scoring that as a hit is the
                               single easiest way to manufacture a track record, so anything inside
                               plus or minus 2% resolves `inconclusive`. Inconclusive is an
                               outcome, not a hedge, and it is shown in the counts rather than
                               quietly dropped from the denominator.
"""
from __future__ import annotations

from datetime import date, datetime

import psycopg

from .. import ledger
from ..backtest.engine import Series, entry_day_after, excess_return, exit_day_for

# One definition, not a second 2%. Bound to the Ledger's floor so the two planes of this product
# can never drift into scoring the same move differently.
NOISE_FLOOR = ledger.NOISE_FLOOR

# The reasons a resolution cannot be completed, in the reader's words. Same distinction the Ledger
# draws: a subject that is not priceable at all, versus a feed that has not caught up. The second
# is our operational fault and says so.
UNSCOREABLE = {
    "no_symbol": "there is no price history for {symbol}, so this call cannot be scored.",
    "no_benchmark": "there are no {benchmark} prices loaded, and every call is measured against "
                    "{benchmark}. This is a gap on our side.",
    "no_entry_price": "our price feed for {symbol} ends before this call was published, so there "
                      "is no entry price. That is a gap in our data rather than a fault in the "
                      "call.",
    "horizon_open_or_delisted": "the price feed for {symbol} does not reach the end of the "
                                "horizon, so there is no exit price yet.",
}


def _series(conn: psycopg.Connection, symbol: str) -> Series:
    with conn.cursor() as cur:
        cur.execute("SELECT day, close FROM prices_eod WHERE symbol = %s ORDER BY day", (symbol,))
        return Series.from_rows(cur.fetchall())


def entry_exit_sessions(published_at: datetime, horizon_days: int, symbol: str,
                        conn: psycopg.Connection) -> tuple[date, date] | None:
    """The two sessions a call is measured between, or None if the series cannot supply both."""
    sym = _series(conn, symbol)
    if not sym.days:
        return None
    entry = entry_day_after(sym, published_at.date())
    if entry is None:
        return None
    exit_session = exit_day_for(sym, entry, horizon_days)
    return (entry, exit_session) if exit_session else None


def verdict_for(direction: str, excess: float | None,
                reason: str | None = None) -> tuple[str, str]:
    """(verdict, a sentence saying why). Thin wrapper over `ledger.verdict_for`.

    The decision itself is the Ledger's, unchanged. What is added here is that the reason is
    ALWAYS present, including on a hit or a miss, where the Ledger returns None because its own
    surfaces render the number beside it. A record page shows one call on its own, and a bare
    verdict with no arithmetic beside it is the thing a sceptic is entitled to distrust.
    """
    verdict, note = ledger.verdict_for(direction, excess, reason)
    if note:
        return verdict, note
    moved = "up" if (excess or 0) > 0 else "down"
    agreed = "as called" if verdict == "hit" else "against the call"
    return verdict, (f"called {direction}, moved {moved} {excess:+.2%} against the benchmark over "
                     f"the horizon, {agreed}.")


def resolve_call(call_id: int, conn: psycopg.Connection, spy: Series | None = None) -> dict:
    """Score one call and write ONLY the resolution columns.

    Writes nothing when the horizon is still open: an unresolved call is an honest state and
    stamping a verdict on it early would be a guess. Writes `unscoreable` with the real reason
    when the prices cannot supply an answer, because a row that stays blank forever reads to a
    sceptic like a result being withheld.
    """
    with conn.cursor() as cur:
        cur.execute("""SELECT symbol, direction, horizon_days, benchmark_symbol, published_at,
                              verdict
                         FROM calls WHERE id = %s""", (call_id,))
        row = cur.fetchone()
    if not row:
        return {"error": f"there is no call {call_id}."}
    symbol, direction, horizon_days, benchmark, published_at, existing = row
    if existing is not None:
        # The trigger would refuse this anyway. Refusing here as well means the scorer reports it
        # rather than raising, so one already-resolved call cannot abort a batch.
        return {"call_id": call_id, "skipped": "already resolved", "verdict": existing}

    sym = _series(conn, symbol)
    spy = spy if spy is not None else _series(conn, benchmark)

    if not spy.days:
        return _write(conn, call_id, "unscoreable",
                      UNSCOREABLE["no_benchmark"].format(benchmark=benchmark), {})
    if not sym.days:
        return _write(conn, call_id, "unscoreable",
                      UNSCOREABLE["no_symbol"].format(symbol=symbol), {})

    as_of = published_at.date()
    excess, why = excess_return(sym, spy, as_of, horizon_days)
    if excess is None:
        if why == "horizon_open_or_delisted" and sym.last_day and spy.last_day:
            # Two very different situations arrive here wearing one label. If the feed simply has
            # not reached the horizon yet, the call is still OPEN and must stay open; sealing it
            # unscoreable would be permanent, and the trigger means permanent really is permanent.
            entry = entry_day_after(sym, as_of)
            if entry and exit_day_for(sym, entry, horizon_days) is None \
                    and min(sym.last_day, spy.last_day) < entry:
                return {"call_id": call_id, "status": "open",
                        "reason": "the price feed has not reached the horizon yet."}
        return _write(conn, call_id, "unscoreable",
                      UNSCOREABLE.get(why, UNSCOREABLE["no_symbol"]).format(
                          symbol=symbol, benchmark=benchmark), {})

    entry = entry_day_after(sym, as_of)
    exit_session = exit_day_for(sym, entry, horizon_days)
    bench_exit = exit_day_for(spy, entry, horizon_days)
    entry_price, exit_price = sym.close[entry], sym.close[exit_session]
    bench_entry_price, bench_exit_price = spy.close[entry], spy.close[bench_exit]
    subject_return = exit_price / entry_price - 1.0
    benchmark_return = bench_exit_price / bench_entry_price - 1.0

    verdict, note = verdict_for(direction, excess)
    return _write(conn, call_id, verdict, note, {
        "entry_session": entry, "exit_session": exit_session,
        "entry_price": entry_price, "exit_price": exit_price,
        "benchmark_entry": bench_entry_price, "benchmark_exit": bench_exit_price,
        "subject_return": round(subject_return, 6),
        "benchmark_return": round(benchmark_return, 6),
        "excess_return": excess,
    })


def _write(conn: psycopg.Connection, call_id: int, verdict: str, note: str,
           measured: dict) -> dict:
    """The only write path in this module, and it touches only resolution columns.

    Spelled out column by column rather than composed, so that the set of writable columns is
    visible in one place and matches the trigger exactly. If a sealed column ever appeared here
    the database would refuse it, which is the point of having both.
    """
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE calls SET entry_session=%s, exit_session=%s, entry_price=%s, exit_price=%s,
                                benchmark_entry=%s, benchmark_exit=%s, subject_return=%s,
                                benchmark_return=%s, excess_return=%s, verdict=%s,
                                verdict_note=%s, resolved_at=now()
                          WHERE id=%s AND verdict IS NULL""",
            (measured.get("entry_session"), measured.get("exit_session"),
             measured.get("entry_price"), measured.get("exit_price"),
             measured.get("benchmark_entry"), measured.get("benchmark_exit"),
             measured.get("subject_return"), measured.get("benchmark_return"),
             measured.get("excess_return"), verdict, note, call_id))
    conn.commit()
    out = {"call_id": call_id, "verdict": verdict, "verdict_note": note}
    for k, v in measured.items():
        out[k] = v.isoformat() if isinstance(v, date) else v
    return out


def resolve_due(conn: psycopg.Connection, limit: int = 100) -> dict:
    """Resolve every call whose horizon has elapsed and which has no verdict yet.

    Returns counts BY VERDICT, not a bare success. A scheduler job that produced nothing is
    recorded as a successful run, which is exactly how a month of zero claim production went
    unnoticed in this codebase before. `job_runs.detail` gets this dict, so the operator can see
    what a run actually did rather than that it did not crash.
    """
    spy = _series(conn, "SPY")
    if not spy.days:
        return {"due": 0, "resolved": 0, "still_open": 0, "nothing_due": True,
                "note": "no SPY prices are loaded, so nothing can be scored. Run ingest-prices "
                        "for SPY first, because it is the benchmark for every call."}

    with conn.cursor() as cur:
        cur.execute("""SELECT id FROM calls
                        WHERE verdict IS NULL
                          AND published_at::date + make_interval(days => horizon_days) <= now()
                     ORDER BY published_at LIMIT %s""", (limit,))
        ids = [r[0] for r in cur.fetchall()]

    counts = {"hit": 0, "miss": 0, "inconclusive": 0, "unscoreable": 0}
    still_open = 0
    for call_id in ids:
        out = resolve_call(call_id, conn, spy=spy)
        if out.get("status") == "open":
            still_open += 1
        elif out.get("verdict") in counts:
            counts[out["verdict"]] += 1

    resolved = sum(counts.values())
    detail = {"due": len(ids), "resolved": resolved, "still_open": still_open,
              "nothing_due": not ids, **counts}
    if not ids:
        detail["note"] = "no call had reached its horizon."
    elif still_open:
        detail["note"] = (f"{still_open} call(s) reached their horizon but the price feed has not, "
                          f"so they stay open rather than being sealed unscoreable.")
    return detail
