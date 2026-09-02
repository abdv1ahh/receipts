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
horizon actually closes. `ledger.py` already draws this exact line between "no price series for
this subject" and "the price feed ends before the claim", for the same reason.
"""
from __future__ import annotations

from datetime import UTC, date, datetime

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
MIN_THESIS_CHARS = 40

# How far behind the benchmark a symbol's last close may sit before publishing warns about it.
# Five sessions is comfortably more than a weekend plus a holiday, so it does not fire on normal
# calendar gaps, and comfortably less than the eleven day backlog a paced top-up leaves behind.
STALE_TOLERANCE_DAYS = 5

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
    if len(thesis) < MIN_THESIS_CHARS:
        problems.append(f"the thesis needs at least {MIN_THESIS_CHARS} characters, so a reader can "
                        f"tell what you actually claimed. This one has {len(thesis)}.")

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
        return {"scoreable": False, "permanent": True, "symbol": symbol,
                "reason": "no symbol was given."}

    sym_last, sym_rows = _last_close(conn, symbol)
    bench_last, bench_rows = _last_close(conn, benchmark)

    if not bench_rows:
        return {"scoreable": False, "permanent": False, "symbol": symbol,
                "benchmark": benchmark, "reason":
                f"there are no {benchmark} prices loaded, and {benchmark} is the benchmark every "
                f"call is measured against. This is a gap on our side, not a problem with your "
                f"symbol."}

    if not sym_rows:
        return {"scoreable": False, "permanent": True, "symbol": symbol,
                "benchmark": benchmark, "benchmark_last_close": bench_last.isoformat(),
                "reason": f"no price series is loaded for {symbol}, so a call on it could never "
                          f"be scored. It will be sealed as unscoreable, with this reason, and "
                          f"published anyway so the record stays complete."}

    behind = (bench_last - sym_last).days if (bench_last and sym_last) else 0
    if behind > STALE_TOLERANCE_DAYS:
        return {"scoreable": False, "permanent": False, "symbol": symbol,
                "benchmark": benchmark, "rows": sym_rows,
                "symbol_last_close": sym_last.isoformat(),
                "benchmark_last_close": bench_last.isoformat(), "days_behind": behind,
                "reason": f"{symbol} has {sym_rows} price rows but the newest is {sym_last}, "
                          f"which is {behind} days behind {benchmark} at {bench_last}. Our price "
                          f"feed is catching up. The call will publish and stay open, and it will "
                          f"be scored once the feed reaches its horizon."}

    return {"scoreable": True, "permanent": False, "symbol": symbol, "benchmark": benchmark,
            "rows": sym_rows, "symbol_last_close": sym_last.isoformat(),
            "benchmark_last_close": bench_last.isoformat(), "days_behind": behind,
            "reason": f"{symbol} has {sym_rows} daily closes through {sym_last} and can be scored "
                      f"against {benchmark}."}


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
_LIST_COLUMNS = sql.SQL(", ").join(map(sql.Identifier, (
    "id", "caller_id", "seq", "symbol", "direction", "horizon_days", "confidence", "thesis",
    "benchmark_symbol", "published_at", "knowable_time", "prev_hash", "content_hash",
    "entry_session", "exit_session", "entry_price", "exit_price", "benchmark_entry",
    "benchmark_exit", "subject_return", "benchmark_return", "excess_return", "verdict",
    "verdict_note", "resolved_at")))


def _row(r: tuple) -> dict:
    num = lambda v: float(v) if v is not None else None            # noqa: E731 — trivial local
    return {
        "id": r[0], "caller_id": r[1], "seq": r[2], "symbol": r[3], "direction": r[4],
        "horizon_days": r[5], "confidence": r[6], "thesis": r[7], "benchmark_symbol": r[8],
        "published_at": r[9].isoformat(), "knowable_time": r[10].isoformat(),
        "prev_hash": r[11], "content_hash": r[12],
        "entry_session": r[13].isoformat() if r[13] else None,
        "exit_session": r[14].isoformat() if r[14] else None,
        "entry_price": num(r[15]), "exit_price": num(r[16]),
        "benchmark_entry": num(r[17]), "benchmark_exit": num(r[18]),
        "subject_return": num(r[19]), "benchmark_return": num(r[20]),
        "excess_return": num(r[21]), "verdict": r[22], "verdict_note": r[23],
        "resolved_at": r[24].isoformat() if r[24] else None,
    }


def listing(caller_id: int, conn: psycopg.Connection) -> list[dict]:
    """Every call by one caller, newest first. The record page's spine."""
    with conn.cursor() as cur:
        cur.execute(sql.SQL("SELECT {cols} FROM calls WHERE caller_id = %s ORDER BY seq DESC")
                    .format(cols=_LIST_COLUMNS), (caller_id,))
        return [_row(r) for r in cur.fetchall()]


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
