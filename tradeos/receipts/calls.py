"""Publishing a call, and deciding honestly whether it can ever be scored.

This module enforces the design decision the whole product rests on: a call that cannot be scored
may not be published in an ambiguous form. There are exactly two failure shapes and they must not
be conflated.

  PERMANENT      the symbol has no price series here and never will under the current sources.
                 A call on it is sealed immediately as `unscoreable`, with the reason, so nobody
                 can point at an unresolved row later and imply it was a pending win.

  OPERATIONAL    the symbol is perfectly scoreable and our price feed is behind. That is our
                 fault, it is fixable, and it usually fixes itself: the free Tiingo tier paces at
                 roughly 45 to 57 symbols an hour, so a top-up pass leaves most of the table days
                 stale while it works through the queue.

Stamping `unscoreable` on the operational case would be a serious error, because the append-only
trigger makes a verdict permanent. A call marked unscoreable at 10am because the feed was eleven
days behind could never be corrected at 11am when the feed caught up. So an operational gap
publishes OPEN, carries a visible warning at publish time, and is decided by the scorer when the
horizon actually closes. `prices.UNSCOREABLE_REASONS` draws this exact line between "no price series for
this subject" and "the price feed ends before the claim", for the same reason.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import psycopg
from psycopg import sql
from psycopg.types.json import Json

from . import chain, context

# The three windows, and no others. A record where every caller picks their own horizon cannot be
# compared across callers, and comparison is the entire purpose of a board.
SCOREABLE_HORIZONS = (7, 30, 90)

DIRECTIONS = ("up", "down")
CONFIDENCES = ("low", "medium", "high")
DEFAULT_BENCHMARK = "SPY"

# A thesis is the part a reader judges. Forty characters is not a quality bar, it is a floor under
# "up" and "looks good", which carry no information a reader could later hold anyone to.
#
# OPTIONAL, BUT SUBSTANTIVE IF GIVEN. The floor used to be mandatory, and on a phone it was the
# single slowest step in publishing a call — a forty-character minimum in a five-row textarea reads
# as an essay, and a caller with a view and thirty seconds abandons rather than writes one. So an
# EMPTY thesis is now allowed and a short one still is not: either say nothing, or say something a
# reader could hold you to. That keeps the exact property the floor was built for (no "up", no
# "looks good") while removing it as a barrier.
#
# The trade is real and is stated rather than hidden: a record whose calls carry no reasoning is
# less useful to a reader than one whose calls do, and the record page says "no reasoning
# published" where that is the case rather than rendering an empty cell. A blank is information
# about the caller too.
MIN_THESIS_CHARS = 40

# How far behind a symbol's last close may sit before publishing warns about it. Five sessions is
# comfortably more than a weekend plus a holiday, so it does not fire on normal calendar gaps, and
# comfortably less than the eleven day backlog a paced top-up leaves behind.
STALE_TOLERANCE_DAYS = 5

# The same question asked of the BENCHMARK, and asked far more strictly, because the two are not
# symmetrical in consequence: one stale symbol affects one call, while a stale benchmark affects
# every call ever published. SPY is also the one symbol fetched first on every top-up (CLAUDE.md
# 0h) precisely for that reason, so any lag at all means the pass that protects it failed. Three
# days covers a long weekend and nothing more.
BENCHMARK_TOLERANCE_DAYS = 3

_ALLOWED_KEYS = {"symbol", "direction", "horizon_days", "confidence", "thesis"}


# ------------------------------------------------------------------ validation (pure)

def validate(spec: dict) -> list[str]:
    """Every problem with a proposed call, in the reader's words. An empty list means valid.

    Returns ALL the problems rather than the first, so a form can show everything at once instead
    of making someone submit five times to discover five faults.
    """
    problems: list[str] = []

    unknown = sorted(set(spec) - _ALLOWED_KEYS)
    if unknown:
        # Refused rather than ignored. A field silently dropped is a caller believing they said
        # something they did not say, and this record has to mean exactly what it shows.
        problems.append(f"these fields are not part of a call and were refused: {', '.join(unknown)}")

    symbol = str(spec.get("symbol") or "").strip().upper()
    if not symbol:
        problems.append("a call needs a symbol.")
    elif len(symbol) > 12 or not all(c.isalnum() or c in ".-" for c in symbol):
        problems.append(f"{symbol!r} does not look like a ticker symbol.")

    if spec.get("direction") not in DIRECTIONS:
        problems.append("direction has to be either up or down.")

    if spec.get("horizon_days") not in SCOREABLE_HORIZONS:
        problems.append("the horizon has to be 7, 30 or 90 days, so records can be compared.")

    if spec.get("confidence") not in CONFIDENCES:
        problems.append("confidence has to be low, medium or high.")

    thesis = str(spec.get("thesis") or "").strip()
    if thesis and len(thesis) < MIN_THESIS_CHARS:
        problems.append(f"a reason is optional, but a short one is worse than none: either leave "
                        f"it empty or write at least {MIN_THESIS_CHARS} characters a reader could "
                        f"hold you to. This one has {len(thesis)}.")

    return problems


def normalise(spec: dict) -> dict:
    """The validated spec in stored form. Call only after `validate` returns empty."""
    return {"symbol": str(spec["symbol"]).strip().upper(),
            "direction": spec["direction"],
            "horizon_days": int(spec["horizon_days"]),
            "confidence": spec["confidence"],
            "thesis": str(spec["thesis"]).strip()}


# ------------------------------------------------------------------ scoreability

def _last_close(conn: psycopg.Connection, symbol: str) -> tuple[date | None, int]:
    with conn.cursor() as cur:
        cur.execute("SELECT max(day), count(*) FROM prices_eod WHERE symbol = %s", (symbol,))
        row = cur.fetchone()
    return (row[0], row[1] or 0) if row else (None, 0)


def scoreability(symbol: str, conn: psycopg.Connection,
                 benchmark: str = DEFAULT_BENCHMARK) -> dict:
    """Can a call on this symbol be scored, and if not, why not, and is that permanent.

    `permanent` is the field that matters. It decides whether publishing seals an `unscoreable`
    verdict on the spot or publishes an open call with a warning. See the module docstring.
    """
    symbol = (symbol or "").strip().upper()
    if not symbol:
        return {"scoreable": False, "permanent": True, "blocks_publish": True, "symbol": symbol,
                "reason": "no symbol was given."}

    sym_last, sym_rows = _last_close(conn, symbol)
    bench_last, bench_rows = _last_close(conn, benchmark)

    if not bench_rows:
        return {"scoreable": False, "permanent": False, "blocks_publish": True,
                "symbol": symbol, "benchmark": benchmark, "reason":
                f"there are no {benchmark} prices loaded, and {benchmark} is the benchmark every "
                f"call is measured against. This is a gap on our side, not a problem with your "
                f"symbol. Please publish again shortly."}

    if not sym_rows:
        return {"scoreable": False, "permanent": True, "blocks_publish": False, "symbol": symbol,
                "benchmark": benchmark, "benchmark_last_session": bench_last.isoformat(),
                "reason": f"no price series is loaded for {symbol}, so a call on it could never "
                          f"be scored. It will be sealed as unscoreable, with this reason, and "
                          f"published anyway so the record stays complete."}

    # SYMMETRIC, measured from whichever side is more current rather than from the benchmark.
    #
    # This was `(bench_last - sym_last).days`, so when the BENCHMARK was the one behind the number
    # went NEGATIVE and sailed through the `> tolerance` check: the Part A proof run measured
    # `days_behind: -25, scoreable: true` while SPY was twenty-five days stale. The gate could see
    # a lagging symbol and was structurally blind to a lagging benchmark, which is the more
    # dangerous of the two by a wide margin.
    #
    # The reference is the newer of the two closes. No extra query, and it directly answers "is
    # one of these two behind the other". A whole feed that has stalled evenly shows 0 here and is
    # caught instead by `scoring.benchmark_health`, which compares against the market's sessions.
    reference = max(sym_last, bench_last)
    symbol_behind = (reference - sym_last).days
    benchmark_behind = (reference - bench_last).days
    common = {"symbol": symbol, "benchmark": benchmark, "rows": sym_rows,
              "symbol_last_session": sym_last.isoformat(),
              "benchmark_last_session": bench_last.isoformat(),
              "days_behind": symbol_behind, "benchmark_days_behind": benchmark_behind}

    # A lagging benchmark BLOCKS the publish rather than publishing open with a warning. Every
    # other gap here is about one symbol and costs one call a few hours of waiting; this one means
    # we cannot price any commitment at all right now. Taking a permanent, sealed commitment while
    # unable to show the caller a trustworthy entry price against it is the wrong trade, and unlike
    # a sealed verdict, a refused publish costs them only the time it takes us to catch up.
    if benchmark_behind > BENCHMARK_TOLERANCE_DAYS:
        return {**common, "scoreable": False, "permanent": False, "blocks_publish": True,
                "reason": f"our {benchmark} series ends {bench_last}, which is {benchmark_behind} "
                          f"days behind {symbol} at {sym_last}. {benchmark} is the benchmark every "
                          f"call is measured against, so we cannot price a commitment right now. "
                          f"This is a gap on our side and it is being caught up — please publish "
                          f"again shortly."}

    if symbol_behind > STALE_TOLERANCE_DAYS:
        return {**common, "scoreable": False, "permanent": False, "blocks_publish": False,
                "reason": f"{symbol} has {sym_rows} price rows but the newest is {sym_last}, "
                          f"which is {symbol_behind} days behind {benchmark} at {bench_last}. Our "
                          f"price feed is catching up. The call will publish and stay open, and it "
                          f"will be scored once the feed reaches its horizon."}

    return {**common, "scoreable": True, "permanent": False, "blocks_publish": False,
            "reason": f"{symbol} has {sym_rows} daily closes through {sym_last} and can be scored "
                      f"against {benchmark}."}


def preview(symbol: str, horizon_days: int, conn: psycopg.Connection,
            now: datetime | None = None, benchmark: str = DEFAULT_BENCHMARK) -> dict:
    """Exactly what a caller is committing to, shown before they commit to it.

    WHAT THIS DELIBERATELY DOES NOT CLAIM, because it cannot: the entry price. Entry is the close of
    the first session STRICTLY AFTER publication (`entry_day_after`), which at publish time has not
    happened — the number does not exist yet and nobody, including us, knows it. Printing the last
    close under the label "entry price" would be the single most damaging small lie this product
    could tell, because the whole proposition is that its numbers mean exactly what they say.

    AND WHAT IT NO LONGER SHOWS, for a different reason. It used to return `last_close` and
    `benchmark_last_close` — the most recent closes we hold for the symbol and for SPY, live from
    `prices_eod` — so a caller could see roughly where they were entering. Those are the vendor's
    prices, and this panel is a screen. `record.NO_PRICES` states the rule; the panel keeps the
    thing that was actually load-bearing, which is how CURRENT our data is, now expressed as the
    date of the last session we hold rather than the number printed at it. A caller deciding
    whether to publish needs to know our feed is four days stale; they do not need our copy of
    the close to learn that, and they can read the price itself anywhere.

    So this returns three true things, which together make the commitment unambiguous:

      the last SESSION we hold  as a date, for the symbol and for the benchmark, so the caller can
                                see how current our data is before taking a permanent commitment
      the entry RULE            stated in words, because the rule is knowable even when the price
                                is not. The date is not asserted either: whether the next session
                                is tomorrow depends on a trading calendar this database does not
                                have, and "the next session after you publish" is exact without one
      the horizon's CALENDAR    plain arithmetic on the horizon, so "when will this be scored" has
        target                  a date attached rather than a duration
    """
    now = now or datetime.now(UTC)
    score = scoreability(symbol, conn, benchmark)
    out = {"symbol": (symbol or "").strip().upper(), "horizon_days": horizon_days,
           "scoreability": score, "published_at": now.isoformat(),
           "horizon_target": (now.date() + timedelta(days=horizon_days)).isoformat(),
           "entry_rule": "You are measured from the close of the first session AFTER you publish, "
                         "never from the session in progress. A call made at 3pm cannot enter at "
                         "that day's close, because most of that close has already happened.",
           "exit_rule": f"The horizon closes on the first session on or after "
                        f"{(now.date() + timedelta(days=horizon_days)).isoformat()}, "
                        f"{horizon_days} days from today.",
           "benchmark": benchmark}
    # `max(day)`, not `day, close ... LIMIT 1`. The close is not selected at all, for the same
    # reason `_LIST_COLUMNS` does not select the six sealed prices: a value never loaded cannot be
    # serialised by the next person to add a field to this payload.
    with conn.cursor() as cur:
        cur.execute("SELECT max(day) FROM prices_eod WHERE symbol = %s",
                    ((symbol or "").strip().upper(),))
        row = cur.fetchone()
        cur.execute("SELECT max(day) FROM prices_eod WHERE symbol = %s", (benchmark,))
        bench = cur.fetchone()
    out["last_session"] = row[0].isoformat() if row and row[0] else None
    out["benchmark_last_session"] = bench[0].isoformat() if bench and bench[0] else None
    return out


# ------------------------------------------------------------------ publishing

def head(conn: psycopg.Connection, caller_id: int) -> tuple[int, str]:
    """(last seq, chain head hash) for one caller. (0, GENESIS_HASH) if they have never published."""
    with conn.cursor() as cur:
        cur.execute("SELECT seq, content_hash FROM calls WHERE caller_id = %s "
                    "ORDER BY seq DESC LIMIT 1", (caller_id,))
        row = cur.fetchone()
    return (row[0], row[1]) if row else (0, chain.GENESIS_HASH)


class PublishError(ValueError):
    """A call that cannot be published at all, with the reasons a reader can act on."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("; ".join(problems))


def publish(caller_id: int, spec: dict, conn: psycopg.Connection,
            now: datetime | None = None) -> dict:
    """Seal one call into the caller's chain and insert it. One transaction, caller row locked.

    The lock is what makes the sequence safe. Two publishes racing would otherwise both read the
    same head, compute the same seq, and chain from the same hash, producing a fork. The UNIQUE
    (caller_id, seq) constraint would catch it, but a lost call and a 500 is a worse answer than
    waiting a few milliseconds.

    `published_at` and `knowable_time` are the SAME instant on purpose. There is no lag between
    making a call and the call being knowable, unlike a filing, and giving them different values
    would invite a later reader to wonder which one the scorer used.
    """
    problems = validate(spec)
    if problems:
        raise PublishError(problems)
    fields = normalise(spec)
    now = now or datetime.now(UTC)

    with conn.cursor() as cur:
        # Lock the caller, and confirm they exist, in one statement.
        cur.execute("SELECT id, user_id FROM callers WHERE id = %s FOR UPDATE", (caller_id,))
        row = cur.fetchone()
        if not row:
            raise PublishError([f"there is no caller {caller_id}."])
        user_id = row[1]

        last_seq, prev_hash = head(conn, caller_id)
        sealed = {"caller_id": caller_id, "seq": last_seq + 1,
                  "benchmark_symbol": DEFAULT_BENCHMARK,
                  "published_at": now, "knowable_time": now, **fields}
        payload, digest = chain.seal(sealed, prev_hash)

        score = scoreability(fields["symbol"], conn)
        if score.get("blocks_publish"):
            # Refused, not published-and-warned. `blocks_publish` is set only where the fault is
            # OURS and affects every call equally (no benchmark prices, or a lagging benchmark),
            # so there is nothing the caller could change about this call to make it work and
            # nothing we could honestly promise about how it would be scored.
            raise PublishError([score["reason"]])
        # Only the PERMANENT case is sealed as unscoreable here. See the module docstring for why
        # the operational case must not be.
        verdict = "unscoreable" if score["permanent"] else None
        verdict_note = score["reason"] if verdict else None

        try:
            snapshot = context.capture(conn, user_id, fields["symbol"], fields["direction"], now)
        except Exception as exc:                     # pragma: no cover - degradation, not logic
            # The context is a nice-to-have; the call is not. A failure to read the Radar must
            # never stop someone publishing, and it must never be recorded as "nothing was live".
            snapshot = context.empty(now, f"the context could not be read ({type(exc).__name__}).")

        cur.execute(
            """INSERT INTO calls (caller_id, seq, symbol, direction, horizon_days, confidence,
                                  thesis, benchmark_symbol, published_at, knowable_time,
                                  prev_hash, content_hash, verdict, verdict_note, resolved_at,
                                  context_snapshot)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               RETURNING id""",
            (caller_id, sealed["seq"], fields["symbol"], fields["direction"],
             fields["horizon_days"], fields["confidence"], fields["thesis"], DEFAULT_BENCHMARK,
             now, now, prev_hash, digest, verdict, verdict_note,
             now if verdict else None, Json(snapshot)))
        call_id = cur.fetchone()[0]
    conn.commit()

    return {"id": call_id, "caller_id": caller_id, "seq": sealed["seq"], **fields,
            "benchmark_symbol": DEFAULT_BENCHMARK,
            "published_at": now.isoformat(), "knowable_time": now.isoformat(),
            "prev_hash": prev_hash, "content_hash": digest, "canonical_payload": payload,
            "verdict": verdict, "verdict_note": verdict_note,
            "scoreability": score, "context_snapshot": snapshot}


# ------------------------------------------------------------------ reading

# The column list is composed with psycopg.sql rather than interpolated into an f-string. It is a
# literal written here and holds nothing a caller supplies, so the risk is theoretical — but the
# repository's rule is that composed SQL goes through psycopg.sql without exceptions, and ruff's
# S608 enforces it. An exception granted for a safe case is how the rule stops being a rule.
#
# THE SIX PRICE COLUMNS ARE NOT SELECTED HERE, and the omission is the enforcement rather than a
# preference. `entry_price`, `exit_price`, `benchmark_entry`, `benchmark_exit`, `subject_return`
# and `benchmark_return` still exist on the row, are still written by `scoring._write` and are
# still sealed by migration 035. They are simply never loaded into anything that can be serialised
# to a reader. `record.NO_PRICES` states why, in the words every surface quotes.
#
# Leaving them out of the SELECT rather than filtering them at the route is deliberate. The leak
# this closes was never a field somebody chose to print: `/api/calls/{id}` returned this row
# wholesale and the prices came with it, invisibly, because all 474 sealed rows had them NULL and
# nothing had yet resolved through the scorer. The first resolution would have started publishing
# them on a public route with no code change and no review. A filter at the edge has the same hole
# one route later; a column that is never read has none.
_LIST_COLUMNS = sql.SQL(", ").join(map(sql.Identifier, (
    "id", "caller_id", "seq", "symbol", "direction", "horizon_days", "confidence", "thesis",
    "benchmark_symbol", "published_at", "knowable_time", "prev_hash", "content_hash",
    "entry_session", "exit_session", "excess_return", "verdict",
    "verdict_note", "resolved_at", "open_reason_code", "open_reason", "open_checked_at")))


def _row(r: tuple) -> dict:
    num = lambda v: float(v) if v is not None else None            # noqa: E731 — trivial local
    return {
        "id": r[0], "caller_id": r[1], "seq": r[2], "symbol": r[3], "direction": r[4],
        "horizon_days": r[5], "confidence": r[6], "thesis": r[7], "benchmark_symbol": r[8],
        "published_at": r[9].isoformat(), "knowable_time": r[10].isoformat(),
        "prev_hash": r[11], "content_hash": r[12],
        # The two session dates are what replaces the four prices, and they are strictly better
        # for the reader: exact, not the vendor's data, and enough to price the same two sessions
        # from any feed and arrive at the same excess return. See `record.RECOMPUTE_NOTE`.
        "entry_session": r[13].isoformat() if r[13] else None,
        "exit_session": r[14].isoformat() if r[14] else None,
        "excess_return": num(r[15]), "verdict": r[16], "verdict_note": r[17],
        "resolved_at": r[18].isoformat() if r[18] else None,
        # Why a past-horizon call is still open. On the row rather than only in a log line: a call
        # thirty days past its horizon showing no verdict and no explanation reads, to a sceptic,
        # exactly like a result being withheld.
        "open_reason_code": r[19], "open_reason": r[20],
        "open_checked_at": r[21].isoformat() if r[21] else None,
    }


# What a row in the "every call" list actually renders. The record page shows the sequence, the
# symbol, the direction, the horizon, the verdict, the excess and the date; it does not show the
# thesis, which is hundreds of characters per call and is read only by the misses panel, which has
# its own bounded query. Sending the full row for every call turned a public page into a full
# serialisation of a caller's entire history, and the house records are already 323 rows.
_SUMMARY_FIELDS = frozenset({
    "id", "caller_id", "seq", "symbol", "direction", "horizon_days", "confidence",
    "benchmark_symbol", "published_at", "content_hash", "excess_return", "verdict", "resolved_at",
    "entry_session", "exit_session",
    # `verdict_note` stays. It is one sentence, and on an `unscoreable` row it is the whole
    # explanation — a reader seeing that chip with no reason beside it has been told less than
    # nothing. The weight was never here: it was `thesis`, several hundred characters per call.
    "verdict_note",
    # And the open-reason trio, for the same reason `verdict_note` is here: an open row past its
    # horizon with nothing beside it is the one state a reader is entitled to be suspicious of.
    "open_reason_code", "open_reason", "open_checked_at",
})


def listing(caller_id: int, conn: psycopg.Connection, full: bool = True) -> list[dict]:
    """Every call by one caller, newest first. The record page's spine.

    `full=False` drops the fields no row in that list renders. Nothing is hidden and no call is
    omitted: the complete row for any single call is one request away at `/api/calls/{id}`, which
    is where the proof panel reads it from.
    """
    with conn.cursor() as cur:
        cur.execute(sql.SQL("SELECT {cols} FROM calls WHERE caller_id = %s ORDER BY seq DESC")
                    .format(cols=_LIST_COLUMNS), (caller_id,))
        rows = [_row(r) for r in cur.fetchall()]
    if full:
        return rows
    return [{k: v for k, v in r.items() if k in _SUMMARY_FIELDS} for r in rows]


def for_chain(caller_id: int, conn: psycopg.Connection) -> list[dict]:
    """Only the sealed fields, in seq order, shaped for `chain.verify_chain`.

    Separate from `listing` on purpose: verification must read the fields the hash was computed
    over and nothing else, so that a bug in the display layer cannot make a broken chain look
    intact.
    """
    with conn.cursor() as cur:
        cur.execute("""SELECT caller_id, seq, symbol, direction, horizon_days, confidence, thesis,
                              benchmark_symbol, published_at, knowable_time, prev_hash,
                              content_hash
                         FROM calls WHERE caller_id = %s ORDER BY seq""", (caller_id,))
        return [dict(zip(chain.SEALED_FIELDS + ("prev_hash", "content_hash"), r, strict=True))
                for r in cur.fetchall()]


def get(call_id: int, conn: psycopg.Connection) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(sql.SQL("SELECT {cols} FROM calls WHERE id = %s").format(cols=_LIST_COLUMNS),
                    (call_id,))
        row = cur.fetchone()
    return _row(row) if row else None
