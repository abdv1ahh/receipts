"""Resolving a call against what actually happened.

The arithmetic is deliberately boring and deliberately borrowed. `backtest.engine.excess_return` is
the one implementation of "how did this move against SPY over this window" in the codebase, and
`prices.verdict_for` is the one implementation of "does that count as a hit". Both are reused here
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
                               quietly dropped from the denominator. The test is STRICT (`<`), so a
                               move that reaches the floor has cleared it.

And one rule added after the Part A proof run, which is the first time this scorer scored calls
this product published:

  A CALL IS SEALED `unscoreable` IF AND ONLY IF WE HOLD NO PRICE SERIES FOR ITS SYMBOL.

Nothing else seals. Not a subject whose feed is behind, not a subject whose series has ended, and
above all not any gap in OUR BENCHMARK. The proof run found that one missing SPY session sealed a
permanent `unscoreable` on a healthy, liquid symbol, carrying a note that named the wrong ticker
and stated something the database contradicted -- and backfilling the SPY row could not correct it,
because the trigger refuses to change a resolved call. That is the product working exactly as
designed on a verdict that should never have been written.

The asymmetry is the whole argument. An open call is visible, honest, retried every six hours and
correctable. A wrong verdict is none of those, permanently. So every ambiguous case waits, and says
on the row itself what it is waiting for.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import psycopg
from psycopg import sql

from .. import prices, stats
from ..backtest.engine import Series, entry_day_after, excess_return, exit_day_for
from ..prices import price_series as _series
from ..prices import truncated_pct

# One definition, not a second 2%. Bound to the Ledger's floor so the two planes of this product
# can never drift into scoring the same move differently.
NOISE_FLOOR = stats.NOISE_FLOOR

# The ONE reason a resolution is sealed. Deliberately a single entry rather than a table: every
# time this dict grew another key, that key became another way to stamp a permanent verdict on an
# operational failure. `no_symbol` is the only one that is a fact about the CALL -- we hold nothing
# for this ticker and never will under the current sources -- and `calls.scoreability` already
# refuses to publish such a call without saying so first.
UNSCOREABLE = {
    "no_symbol": "there is no price history for {symbol}, so this call cannot be scored.",
}

# Why a call past its horizon is still open, in the reader's words. Stored on the row (migration
# 036) rather than only logged, because a call thirty days past its stated horizon showing no
# verdict and no explanation is indistinguishable, to a sceptic, from a result being withheld.
#
# These are keyed to `open_reason_code`'s CHECK constraint. Adding one needs the migration too.
OPEN_REASONS = {
    "waiting_for_benchmark":
        "this call is measured against {benchmark}, and our {benchmark} series is missing a "
        "session it needs ({detail}). That is a gap on our side, not a problem with {symbol} or "
        "with the call. It is retried every few hours and will be scored once the gap is filled.",
    "waiting_for_subject_price":
        "our price feed for {symbol} has not reached the end of this call's horizon yet — its "
        "newest close is {detail}. The call stays open rather than being scored on data we do not "
        "have, and is retried every few hours.",
    "subject_series_ended":
        "our price feed for {symbol} stops at {detail}, well before {benchmark} did, which usually "
        "means the symbol stopped trading. We do not seal a verdict on that, because we cannot "
        "tell a delisting from a feed that has given up, and a sealed verdict could never be "
        "corrected. The call stays open and visible.",
}

# The reasons that are OURS rather than the subject's. `excess_return` distinguishes four causes;
# these two are facts about our benchmark ingestion and can never decide a call.
_BENCHMARK_REASONS = ("no_benchmark_entry_price", "no_benchmark_exit_price")

# How far the subject's last close may sit behind the benchmark's before "behind" reads as "ended".
# A disclosure threshold, not a verdict threshold -- see `_open_reason_for`.
SERIES_ENDED_TOLERANCE_DAYS = 10

# A day is a market session if this many symbols traded it, and this share of the symbols active in
# the window. Both, so one bad row on a non-session day cannot invent a session, and a thin window
# cannot hide a real one.
MARKET_SESSION_MIN_SYMBOLS = 3
MARKET_SESSION_MIN_SHARE = 0.10

# How far back `benchmark_health` looks when nothing narrower is asked for: comfortably past the
# longest horizon, so a hole that could still affect a due call is in range.
BENCHMARK_WINDOW_DAYS = 400


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
    """(verdict, a sentence saying why). Thin wrapper over `prices.verdict_for`.

    The decision itself is the Ledger's, unchanged. What is added here is that the reason is
    ALWAYS present, including on a hit or a miss, where the Ledger returns None because its own
    surfaces render the number beside it. A record page shows one call on its own, and a bare
    verdict with no arithmetic beside it is the thing a sceptic is entitled to distrust.
    """
    verdict, note = prices.verdict_for(direction, excess, reason)
    if note:
        return verdict, note
    moved = "up" if (excess or 0) > 0 else "down"
    agreed = "as called" if verdict == "hit" else "against the call"
    return verdict, (f"called {direction}, moved {moved} {truncated_pct(excess)} against the "
                     f"benchmark over the horizon, {agreed}.")




# ------------------------------------------------------------------ is the benchmark trustworthy

def market_sessions(conn: psycopg.Connection, since: date) -> list[date]:
    """Every day on or after `since` that the market was open, judged by how many symbols traded.

    There is no trading-calendar table here and adding one would be a dependency for a question the
    price table can already answer: a day several hundred symbols have a close on was a session.
    Two thresholds rather than one, because a single bad row on a public holiday must not invent a
    session (which would make the benchmark look holed and refuse every batch), and a narrow window
    with few active symbols must not hide a real one.
    """
    with conn.cursor() as cur:
        cur.execute(
            """WITH active AS (SELECT count(DISTINCT symbol) AS n FROM prices_eod WHERE day >= %s)
               SELECT day FROM prices_eod WHERE day >= %s
                GROUP BY day
                HAVING count(*) >= GREATEST(%s, ceil(%s * (SELECT n FROM active)))
                ORDER BY day""",
            (since, since, MARKET_SESSION_MIN_SYMBOLS, MARKET_SESSION_MIN_SHARE))
        return [r[0] for r in cur.fetchall()]


def benchmark_health(conn: psycopg.Connection, benchmark: str = "SPY",
                     since: date | None = None) -> dict:
    """Whether the benchmark series can be trusted to settle anything, and if not, which dates.

    Two faults, and both are unambiguously OURS rather than the market's, which is what makes it
    safe to act on them:

      A HOLE.       The market traded a session the benchmark has no row for. SPY trades every day
                    the market is open, so this is always an ingestion gap. It is the exact trigger
                    the Part A proof run used to seal a permanent wrong verdict.
      A SHORT TAIL. The benchmark's newest close is older than the market's. Same reasoning, and
                    CLAUDE.md 0h is why it happens: SPY is fetched FIRST on every top-up precisely
                    because a stale benchmark unscoreables everything, so when SPY is the one
                    behind, the pass that was supposed to protect it failed.

    Note what this deliberately does NOT report as a fault: a benchmark that is level with the
    market but has not yet reached some call's horizon. That is not a gap, it is a horizon that has
    not closed, and it is decided per call rather than by refusing the batch.
    """
    spy = _series(conn, benchmark)
    if not spy.days:
        return {"ok": False, "benchmark": benchmark, "last_session": None, "market_last": None,
                "missing_sessions": [],
                "reason": f"there are no {benchmark} prices loaded at all, and every call is "
                          f"measured against {benchmark}. Nothing can be scored until that is "
                          f"fixed, and nothing will be sealed in the meantime."}

    since = since or (spy.days[-1] - timedelta(days=BENCHMARK_WINDOW_DAYS))
    sessions = market_sessions(conn, since)
    missing = [d for d in sessions if d not in spy.close]
    market_last = sessions[-1] if sessions else None
    behind = (market_last - spy.days[-1]).days if market_last else 0

    if missing:
        shown = ", ".join(d.isoformat() for d in missing[:5])
        more = f" and {len(missing) - 5} more" if len(missing) > 5 else ""
        return {"ok": False, "benchmark": benchmark, "last_session": spy.days[-1].isoformat(),
                "market_last": market_last.isoformat() if market_last else None,
                "missing_sessions": [d.isoformat() for d in missing],
                "reason": f"our {benchmark} series is missing {len(missing)} session(s) the market "
                          f"traded ({shown}{more}). {benchmark} trades every session, so this is a "
                          f"gap in our ingestion. No call will be scored until it is filled, "
                          f"because a benchmark with holes produces wrong verdicts and a verdict "
                          f"cannot be taken back."}
    if behind > 0:
        return {"ok": False, "benchmark": benchmark, "last_session": spy.days[-1].isoformat(),
                "market_last": market_last.isoformat(), "missing_sessions": [],
                "reason": f"our {benchmark} series ends {spy.days[-1]} but the market traded "
                          f"through {market_last}, so the benchmark is {behind} day(s) behind. "
                          f"Nothing is scored against a lagging benchmark."}
    return {"ok": True, "benchmark": benchmark, "last_session": spy.days[-1].isoformat(),
            "market_last": market_last.isoformat() if market_last else None,
            "missing_sessions": [],
            "reason": f"{benchmark} holds every one of the {len(sessions)} sessions the market "
                      f"traded since {since}."}


# ------------------------------------------------------------------ why a call is still open

def _open_reason_for(why: str, symbol: str, benchmark: str, sym: Series,
                     spy: Series) -> tuple[str, str]:
    """(code, sentence) for a call that cannot be scored yet. Never seals anything.

    The delisted-versus-merely-behind judgement lives HERE, on an editable disclosure column, and
    nowhere near a verdict. CLAUDE.md 0z forbids letting the benchmark settle a VERDICT -- SPY
    reaches the horizon, the symbol does not, therefore the symbol is dead -- because a symbol
    lagging SPY is the routine state of this table and that reasoning would seal ordinary calls an
    hour before their prices arrived. It does not forbid SAYING WHAT THE DATA LOOKS LIKE. The
    difference is that this sentence is replaced on the next pass and a verdict is not.
    """
    if why in _BENCHMARK_REASONS:
        detail = ("the entry session" if why == "no_benchmark_entry_price"
                  else f"nothing on or after the horizon; newest close {spy.last_day}")
        return "waiting_for_benchmark", OPEN_REASONS["waiting_for_benchmark"].format(
            benchmark=benchmark, symbol=symbol, detail=detail)

    gap = (spy.last_day - sym.last_day).days if (spy.last_day and sym.last_day) else 0
    if gap > SERIES_ENDED_TOLERANCE_DAYS:
        return "subject_series_ended", OPEN_REASONS["subject_series_ended"].format(
            symbol=symbol, benchmark=benchmark, detail=sym.last_day)
    return "waiting_for_subject_price", OPEN_REASONS["waiting_for_subject_price"].format(
        symbol=symbol, benchmark=benchmark, detail=sym.last_day)


def _stay_open(conn: psycopg.Connection, call_id: int, code: str, note: str) -> dict:
    """Record WHY a past-horizon call is still open. Touches no sealed column and no verdict.

    `open_checked_at` matters as much as the reason: "past its horizon, still open, last checked
    four hours ago" is what stops a reader reading an open call as a withheld result. The UPDATE
    carries `verdict IS NULL` so it can never write onto a resolved row even if it is called by
    mistake.
    """
    with conn.cursor() as cur:
        cur.execute("""UPDATE calls SET open_reason_code=%s, open_reason=%s, open_checked_at=now()
                        WHERE id=%s AND verdict IS NULL""", (code, note, call_id))
        written = cur.rowcount
    conn.commit()
    return {"call_id": call_id, "status": "open", "open_reason_code": code, "reason": note,
            **({} if written == 1 else {"no_op": True})}


# ------------------------------------------------------------------ scoring one call

def resolve_call(call_id: int, conn: psycopg.Connection, spy: Series | None = None) -> dict:
    """Score one call, or record why it cannot be scored yet. Writes only non-sealed columns.

    Every path out of here is one of exactly four things, and the list is short on purpose:

      a verdict     the prices answered. Sealed, permanent, with the arithmetic beside it.
      open          anything ambiguous. The reason is stored on the row and retried.
      unscoreable   we hold no price series for this symbol. The only sealing failure.
      skipped       the call already has a verdict. Reported, never raised, so one resolved call
                    cannot abort a batch.
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
        return {"call_id": call_id, "skipped": "already resolved", "verdict": existing}

    sym = _series(conn, symbol)
    spy = spy if spy is not None else _series(conn, benchmark)

    # An absent benchmark is the most operational failure there is, and it is OURS. `resolve_due`
    # refuses the whole batch on it, but a guard one layer up is not the same as a rule: Part A
    # proved `resolve_call`, called directly, sealed `unscoreable` here.
    if not spy.days:
        return _stay_open(conn, call_id, "waiting_for_benchmark",
                          OPEN_REASONS["waiting_for_benchmark"].format(
                              benchmark=benchmark, symbol=symbol,
                              detail=f"we hold no {benchmark} prices at all"))

    # The one permanent fact about a call that prices can establish: there is no series, so there
    # is nothing to measure and there never will be under the current sources.
    if not sym.days:
        return _write(conn, call_id, "unscoreable",
                      UNSCOREABLE["no_symbol"].format(symbol=symbol), {})

    as_of = published_at.date()
    excess, why = excess_return(sym, spy, as_of, horizon_days)
    if excess is None:
        # NOTHING here seals. Four causes arrive, two of them ours and two of them the subject's,
        # and not one of them is a statement about whether the call was right. See the module
        # docstring for what it cost to learn that.
        code, note = _open_reason_for(why, symbol, benchmark, sym, spy)
        return _stay_open(conn, call_id, code, note)

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
    """The only verdict-writing path in this module, and it touches only resolution columns.

    Spelled out column by column rather than composed, so that the set of writable columns is
    visible in one place and matches the trigger exactly. If a sealed column ever appeared here
    the database would refuse it, which is the point of having both.

    `rowcount` IS CHECKED, and that is not defensive tidiness. The UPDATE carries
    `AND verdict IS NULL`, so on an already-resolved call it correctly matches nothing -- and this
    function used to return a success dict anyway, naming a verdict the row never received. Part A
    got back `verdict='hit', excess_return=0.99` while the database held `('unscoreable', None)`.
    `resolve_due` counts these return values into `job_runs.detail`, so a run that wrote nothing
    could report hits, which is precisely the kind of quiet lie this product exists to refuse.

    The open-reason columns are nulled in the same statement: a resolved call has no open reason,
    and 036 freezes them alongside the figures so a stale excuse cannot be attached afterwards.
    """
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE calls SET entry_session=%s, exit_session=%s, entry_price=%s, exit_price=%s,
                                benchmark_entry=%s, benchmark_exit=%s, subject_return=%s,
                                benchmark_return=%s, excess_return=%s, verdict=%s,
                                verdict_note=%s, resolved_at=now(),
                                open_reason_code=NULL, open_reason=NULL, open_checked_at=NULL
                          WHERE id=%s AND verdict IS NULL""",
            (measured.get("entry_session"), measured.get("exit_session"),
             measured.get("entry_price"), measured.get("exit_price"),
             measured.get("benchmark_entry"), measured.get("benchmark_exit"),
             measured.get("subject_return"), measured.get("benchmark_return"),
             measured.get("excess_return"), verdict, note, call_id))
        written = cur.rowcount
    conn.commit()
    if written != 1:
        return {"call_id": call_id, "no_op": True,
                "reason": "this call already carries a verdict, so nothing was written. A verdict "
                          "is written once; see the append-only trigger."}
    out = {"call_id": call_id, "verdict": verdict, "verdict_note": note}
    for k, v in measured.items():
        out[k] = v.isoformat() if isinstance(v, date) else v
    return out


# ------------------------------------------------------------------ the batch

def resolve_due(conn: psycopg.Connection, limit: int = 100,
                caller_id: int | None = None) -> dict:
    """Resolve every call whose horizon has elapsed and which has no verdict yet.

    Returns counts BY VERDICT, not a bare success. A scheduler job that produced nothing is
    recorded as a successful run, which is exactly how a month of zero claim production went
    unnoticed in this codebase before. `job_runs.detail` gets this dict, so the operator can see
    what a run actually did rather than that it did not crash, and `scheduler.run_status` reads
    `resolved` out of it to decide whether a silent run is worth a warning.

    REFUSES THE WHOLE BATCH on a benchmark fault. Not per call -- a holed or lagging benchmark is
    one fault that affects every call at once, and scoring the ones it happens not to touch while
    silently deferring the rest hides it. Refusing is always recoverable: the calls stay open, the
    reason is named with its dates in `job_runs.detail`, and the next pass scores everything once
    the gap is filled.

    `caller_id` SCOPES THE BATCH, and it exists because of a measured accident rather than a
    feature request. This is a batch over the WHOLE table, and the suite runs against the live
    database: `test_resolve_due_counts_no_ops_separately` called it unscoped while `_series` was
    monkeypatched to a fixture, so it picked up @a-real-stranger's real, public, open ABT call and
    wrote that call's public "why is this still open" sentence from fixture prices. Measured
    2026-09-23: the row on the live board read "its newest close is 2026-08-14" while ABT's actual
    series ran to 2026-09-22.

    Nothing sealed was touched -- `_stay_open` writes only disclosure columns -- but the same path
    reaches `_write`, and under a fixture series that happened to span the horizon it would have
    sealed a PERMANENT VERDICT on a stranger's public call from prices that are not real. A verdict
    cannot be taken back (CLAUDE.md 0z), so the near miss is the whole argument. Production passes
    nothing and behaves exactly as before; tests pass their own scratch caller.
    """
    scope = sql.SQL("AND caller_id = {}").format(sql.Placeholder()) if caller_id else sql.SQL("")
    params = ((caller_id, limit) if caller_id else (limit,))
    with conn.cursor() as cur:
        cur.execute(sql.SQL("""SELECT id, published_at::date FROM calls
                                WHERE verdict IS NULL
                                  AND published_at::date
                                      + make_interval(days => horizon_days) <= now()
                                  {scope}
                             ORDER BY published_at LIMIT {lim}""").format(
            scope=scope, lim=sql.Placeholder()), params)
        due = cur.fetchall()
    ids = [r[0] for r in due]

    counts = {"hit": 0, "miss": 0, "inconclusive": 0, "unscoreable": 0}
    base = {"due": len(ids), "resolved": 0, "still_open": 0, "no_ops": 0,
            "nothing_due": not ids, **counts}

    # Checked even with an empty queue, so an operator running this by hand on a quiet board still
    # learns the benchmark is broken rather than being told there was nothing to do.
    health = benchmark_health(conn, since=min((d for _, d in due), default=None))
    if not health["ok"]:
        return {**base, "refused": True, "warning": health["reason"],
                "benchmark_last_session": health["last_session"],
                "market_last_session": health["market_last"],
                "missing_benchmark_sessions": health["missing_sessions"],
                "note": f"nothing was scored. {health['reason']}"}

    if not ids:
        return {**base, "note": "no call had reached its horizon.",
                "benchmark_last_session": health["last_session"]}

    spy = _series(conn, "SPY")
    still_open = no_ops = 0
    for call_id in ids:
        out = resolve_call(call_id, conn, spy=spy)
        if out.get("no_op"):
            no_ops += 1
        elif out.get("status") == "open":
            still_open += 1
        elif out.get("verdict") in counts and not out.get("skipped"):
            counts[out["verdict"]] += 1
        else:
            # Neither scored, nor open, nor a no-op: an already-resolved row that slipped into the
            # queue, or a call that vanished. Counted as a no-op rather than dropped, because
            # `due` must always equal what the run says it did with each one.
            no_ops += 1

    resolved = sum(counts.values())
    detail = {**base, "resolved": resolved, "still_open": still_open, "no_ops": no_ops,
              **counts, "benchmark_last_session": health["last_session"]}
    if still_open:
        detail["note"] = (f"{still_open} call(s) reached their horizon but the prices have not, so "
                          f"they stay open with a stored reason rather than being sealed.")
    return detail
