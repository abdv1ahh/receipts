"""Composing the public record: counts, intervals, calibration, and the board.

Every statistic here already exists in `ledger.py` and `backtest/engine.py` and is imported rather
than rewritten. That is not tidiness. This product's only asset is that its numbers are the same
numbers everywhere, and the fastest way to lose that is a second Wilson interval.

THE SAMPLE GATE IS THE MOST IMPORTANT THING IN THIS FILE. Below 25 resolved scoreable calls, no
hit rate is returned at all: `hit_rate` is None and the surfaces render counts. A percentage on
nine calls is not a weaker version of a percentage on nine hundred, it is a different kind of
statement, and every scoreboard that has ever misled anybody did it by printing the first as
though it were the second. `ledger.py` already refuses percentages on thin slices and
`backtest/engine.py` carries MIN_EPISODES for the same reason; this is the same discipline with
the same reasoning, applied to a public record.

What the gate is NOT is a hiding place. A gated caller still shows every count, every call, and
every miss. What is withheld is one derived number that the sample cannot support.
"""
from __future__ import annotations

import psycopg
from psycopg import sql

from .. import ledger
from ..backtest.engine import wilson_interval
from . import calls as calls_mod
from . import chain, scoring

SAMPLE_GATE = 25

# Where a percentage stops being unsayable and starts being merely uncertain. Stated so the
# methodology page can quote the reasoning instead of the number appearing as an arbitrary 25.
GATE_REASON = ("A hit rate is not shown until 25 calls have resolved as a hit or a miss. Below "
               "that the interval around any rate is wider than the differences a reader would "
               "be trying to judge, so a percentage would suggest a precision the sample cannot "
               "support. The counts are shown instead, and every call is listed.")

# Composed with psycopg.sql for the same reason as the column list in calls.py: the scope fragments
# below are literals written in this module, never anything a caller supplies, and the rule that
# composed SQL goes through psycopg.sql holds regardless.
_COUNT_SQL = sql.SQL("""
    SELECT count(*) FILTER (WHERE verdict = 'hit'),
           count(*) FILTER (WHERE verdict = 'miss'),
           count(*) FILTER (WHERE verdict = 'inconclusive'),
           count(*) FILTER (WHERE verdict = 'unscoreable'),
           count(*) FILTER (WHERE verdict IS NULL)
      FROM calls WHERE {scope}
""")

# The return of FOLLOWING a call: the excess return signed by the direction that was called, so a
# correct down call contributes a positive number. Identical to the Ledger's own definition, and
# the reason expectancy and hit rate can disagree is that this one weighs each call while the
# other only counts it.
_FOLLOWED_SQL = sql.SQL("""
    SELECT CASE WHEN direction = 'up' THEN excess_return ELSE -excess_return END
      FROM calls
     WHERE {scope} AND verdict IN ('hit', 'miss') AND excess_return IS NOT NULL
""")


def _stats(conn: psycopg.Connection, scope_sql: sql.SQL, params: tuple) -> dict:
    """The record for whatever `scope_sql` selects. One caller, or every house caller pooled.

    `scope_sql` is a literal fragment written in this module and never built from user input; the
    values it compares against always arrive as bound parameters.
    """
    with conn.cursor() as cur:
        cur.execute(_COUNT_SQL.format(scope=scope_sql), params)
        counts = cur.fetchone()
        cur.execute(_FOLLOWED_SQL.format(scope=scope_sql), params)
        followed = [float(r[0]) for r in cur.fetchall()]
    return _compute(counts, followed)


def _compute(counts: tuple, followed: list[float]) -> dict:
    """The statistics themselves, pure, over one caller's rows.

    Separated from the fetch so the board can read every caller in two grouped queries and still
    run exactly this code per caller. The alternative is a second implementation of the gate and
    the intervals for the list view, which is how a board and a record page come to disagree about
    the same caller.
    """
    hit, miss, inconclusive, unscoreable, open_calls = counts

    scoreable = hit + miss
    gated = scoreable < SAMPLE_GATE
    ci = ledger.mean_ci(followed)
    wilson = wilson_interval(hit, scoreable) if scoreable else None

    return {
        "counts": {"hit": hit, "miss": miss, "inconclusive": inconclusive,
                   "unscoreable": unscoreable, "open": open_calls},
        "resolved_scoreable": scoreable,
        "hit_rate": None if gated else round(hit / scoreable, 4),
        "hit_rate_ci": None if gated else list(wilson) if wilson else None,
        "expectancy": None if gated else ci["mean"],
        "expectancy_ci": None if gated else [ci["lo"], ci["hi"]],
        # Reported whichever way it points, and reported as NOT significant whenever the interval
        # spans zero. An average that cannot be told apart from no effect is not an effect.
        "expectancy_significant": (not gated) and ci["significant"],
        "expectancy_sd": ci["sd"],
        "z_vs_coinflip": None if gated else ledger.proportion_z(hit, scoreable),
        # Printed next to the sample actually held, so "we do not know yet" comes with a number
        # attached rather than being an excuse.
        "sample_needed_1pct": ledger.sample_needed(ci["sd"] or 0, 0.01),
        "gated": gated,
        "gate_reason": GATE_REASON if gated else None,
        # The gate, and HOW FAR OFF IT IS. Returned rather than left for a surface to subtract,
        # because a caller with three resolved calls and no percentage has no way to tell "the
        # sample is too thin" from "this product is broken" — and the second reading is the one a
        # blank number invites. `remaining_to_gate` is 0 once the rate is published, so a surface
        # can render the same component either side of the line.
        "sample_gate": SAMPLE_GATE,
        "remaining_to_gate": max(0, SAMPLE_GATE - scoreable),
    }


def summary(caller_id: int, conn: psycopg.Connection) -> dict:
    return _stats(conn, sql.SQL("caller_id = %s"), (caller_id,))


def house_summary(conn: psycopg.Connection) -> dict:
    """Every house caller pooled into one record.

    Pooling needs a justification, and here it has one. The house callers are the two registered
    versions of a single scoring function, and v4's own changelog in `signal_definitions` records
    "NO BEHAVIOURAL CHANGE": it was re-registered because a lint pass moved the module hash, not
    because the logic moved. Two version rows, one model. Pooling versions of one model is
    legitimate; pooling two different models would not be, and nothing here does that.
    """
    return _stats(conn, sql.SQL("caller_id IN (SELECT id FROM callers WHERE is_house)"), ())


def calibration(caller_id: int, conn: psycopg.Connection) -> list[dict]:
    """Stated confidence against what actually happened, per bucket.

    A hit rate says how often; calibration says whether the caller knows WHEN they are likely to be
    right, which is the more useful question and the one a hit rate cannot answer. Someone who is
    right 45% of the time overall but 70% of the time on their high confidence calls is worth
    reading. Someone whose high confidence calls do worse than their low confidence ones is not,
    however good their headline looks.

    The numeric ranges come from `ledger.CONFIDENCE_BUCKETS` so that low, medium and high mean the
    same thing on this record as they do in the Ledger. Calls store the bucket as text rather than
    a probability, so there is nothing to bucket here, only a shared vocabulary to honour.
    """
    ranges = {name: [lo, hi] for lo, hi, name in ledger.CONFIDENCE_BUCKETS}
    with conn.cursor() as cur:
        cur.execute("""SELECT confidence,
                              count(*) FILTER (WHERE verdict = 'hit'),
                              count(*) FILTER (WHERE verdict = 'miss')
                         FROM calls
                        WHERE caller_id = %s AND verdict IN ('hit', 'miss')
                     GROUP BY 1""", (caller_id,))
        rows = {c: (h, m) for c, h, m in cur.fetchall()}

    out = []
    for _lo, _hi, name in ledger.CONFIDENCE_BUCKETS:
        hit, miss = rows.get(name, (0, 0))
        n = hit + miss
        wilson = wilson_interval(hit, n) if n else None
        sufficient = n >= SAMPLE_GATE
        out.append({"stated": name, "stated_range": ranges[name], "hit": hit, "miss": miss, "n": n,
                    "observed": round(hit / n, 4) if (n and sufficient) else None,
                    "observed_ci": list(wilson) if (wilson and sufficient) else None,
                    "sufficient": sufficient})
    return out


def recent_misses(caller_id: int, limit: int, conn: psycopg.Connection) -> list[dict]:
    """The misses, newest first.

    A separate function because the record page leads with them. `ledger.jsx` already does this and
    it is the whole argument: a scoreboard that shows you its losses first is making a claim about
    itself that a scoreboard showing wins first cannot make.
    """
    with conn.cursor() as cur:
        cur.execute("""SELECT id, seq, symbol, direction, horizon_days, confidence, thesis,
                              excess_return, exit_session, published_at, verdict_note
                         FROM calls
                        WHERE caller_id = %s AND verdict = 'miss'
                     ORDER BY published_at DESC LIMIT %s""", (caller_id, limit))
        return [{"id": r[0], "seq": r[1], "symbol": r[2], "direction": r[3], "horizon_days": r[4],
                 "confidence": r[5], "thesis": r[6],
                 "excess_return": float(r[7]) if r[7] is not None else None,
                 "exit_session": r[8].isoformat() if r[8] else None,
                 "published_at": r[9].isoformat(), "verdict_note": r[10]}
                for r in cur.fetchall()]


# What a reader is told about WHO holds a handle, in one place so both the React record page and
# the server-rendered share page say the same words. A formatter duplicated across surfaces drifts,
# and the copy that drifts is the one that overstates (CLAUDE.md 0b2).
#
# Two independent things are unproven and they are usually confused:
#
#   AUDIENCE    `callers.verified_at` — has this person shown they control the newsletter, site or
#               account they claim? The flow exists; the reviewer queue has no interface yet.
#   ACCOUNT     `users.email_verified_at` — has anyone confirmed the address behind the login? With
#               no SMTP configured there is no verification flow at all, so this is false for every
#               human caller and will stay false until mail is configured. Registration is open, so
#               saying nothing would leave a reader assuming more than we know.
#
# The sentence has to carry the distinction that matters more than either: the CALLS are sealed and
# checkable whatever the identity turns out to be. An unverified identity is a reason to discount
# who is speaking, not a reason to doubt the record.
_IDENTITY_HOUSE = ("This is one of our own records, published by our signal engine rather than by "
                   "a person.")
_IDENTITY_UNVERIFIED = (
    "Nobody has verified who holds this handle. There is no email confirmation on this account and "
    "the audience link has not been proved, so treat the identity as unconfirmed. The calls "
    "themselves are sealed and every hash can be recomputed here, which is the part that does not "
    "depend on trusting them or us.")
_IDENTITY_AUDIENCE_ONLY = (
    "This handle has proved it controls the audience it claims. The email address behind the "
    "account has not been confirmed — there is no mail flow configured yet — so that part of the "
    "identity is still unverified.")


def identity_note(is_house: bool, audience_verified: bool, account_verified: bool) -> str:
    """The one sentence a reader gets about who is speaking. Pure."""
    if is_house:
        return _IDENTITY_HOUSE
    if audience_verified and not account_verified:
        return _IDENTITY_AUDIENCE_ONLY
    if audience_verified:
        return "This handle has proved it controls the audience it claims."
    return _IDENTITY_UNVERIFIED


def caller(handle: str, conn: psycopg.Connection) -> dict | None:
    with conn.cursor() as cur:
        cur.execute("""SELECT c.id, c.user_id, c.handle, c.display_name, c.bio, c.kind,
                              c.is_house, c.audience_url, c.verified_at, c.verification_method,
                              c.verification_evidence_url, c.created_at,
                              u.email_verified_at IS NOT NULL
                         FROM callers c
                         LEFT JOIN users u ON u.id = c.user_id
                        WHERE lower(c.handle) = lower(%s)""", (handle,))
        r = cur.fetchone()
    if not r:
        return None
    # `user_id IS NULL` for the two house callers, so the LEFT JOIN yields NULL rather than False.
    account_verified = bool(r[12])
    return {"id": r[0], "user_id": r[1], "handle": r[2], "display_name": r[3], "bio": r[4],
            "kind": r[5], "is_house": r[6], "audience_url": r[7],
            "verified_at": r[8].isoformat() if r[8] else None, "verification_method": r[9],
            "verification_evidence_url": r[10], "created_at": r[11].isoformat(),
            "account_verified": account_verified,
            "identity_note": identity_note(r[6], r[8] is not None, account_verified)}


def board(conn: psycopg.Connection) -> list[dict]:
    """Every caller with their record.

    Ordering, and what it does and does not mean. Callers past the gate are ordered by hit rate and
    carry a rank; callers below it carry counts, a Low N label, and NO rank at all, because a rank
    implies a comparison the sample cannot support.

    The rank measures ONE thing: how often past statements turned out right, against SPY, over the
    caller's own stated horizons. It is not a forecast and it is not a recommendation. Note that
    hit rate and expectancy genuinely disagree in this data, so both are returned and a surface
    that shows one without the other is misreporting; the Ledger learned this the hard way at 412
    calls, where the frequency was significantly below chance while the returns cancelled out.
    """
    with conn.cursor() as cur:
        cur.execute("""SELECT id, handle, display_name, kind, is_house, verified_at,
                              verification_method, audience_url
                         FROM callers ORDER BY created_at""")
        rows = cur.fetchall()

    # Two queries for the whole board rather than two per caller.
    with conn.cursor() as cur:
        cur.execute("""SELECT caller_id,
                              count(*) FILTER (WHERE verdict = 'hit'),
                              count(*) FILTER (WHERE verdict = 'miss'),
                              count(*) FILTER (WHERE verdict = 'inconclusive'),
                              count(*) FILTER (WHERE verdict = 'unscoreable'),
                              count(*) FILTER (WHERE verdict IS NULL)
                         FROM calls GROUP BY caller_id""")
        counts = {r[0]: r[1:] for r in cur.fetchall()}
        cur.execute("""SELECT caller_id,
                              CASE WHEN direction = 'up' THEN excess_return ELSE -excess_return END
                         FROM calls
                        WHERE verdict IN ('hit', 'miss') AND excess_return IS NOT NULL""")
        followed: dict[int, list[float]] = {}
        for cid, value in cur.fetchall():
            followed.setdefault(cid, []).append(float(value))

    entries = []
    for cid, handle, name, kind, is_house, verified_at, method, audience in rows:
        entries.append({
            "id": cid, "handle": handle, "display_name": name, "kind": kind,
            "is_house": is_house, "verified": verified_at is not None,
            "verification_method": method, "audience_url": audience,
            "summary": _compute(counts.get(cid, (0, 0, 0, 0, 0)), followed.get(cid, [])),
        })

    ranked = sorted((e for e in entries if not e["summary"]["gated"]),
                    key=lambda e: e["summary"]["hit_rate"], reverse=True)
    for i, e in enumerate(ranked, start=1):
        e["rank"] = i
    for e in entries:
        e.setdefault("rank", None)

    # Ranked first, then the gated ones in the order they joined. A gated caller placed among the
    # ranks by accident of sort order would read as a rank.
    return ranked + [e for e in entries if e["summary"]["gated"]]


def methodology() -> dict:
    """The scoring rules as data, so no surface ever hardcodes them.

    A methodology page written by hand drifts from the code the first time a constant changes, and
    the drift is invisible: the page still reads correctly, it is just no longer true. Everything
    here is read from the same constants the scorer uses.
    """
    return {
        "entry": ("A call enters at the close of the first trading session strictly after it was "
                  "published. Never the session in progress: by the time a call is published, most "
                  "of that day's move has already happened, and entering at that close would "
                  "credit the caller with it."),
        "exit": (f"A call exits at the close of the first trading session on or after its horizon "
                 f"in calendar days. Horizons are {', '.join(str(h) for h in calls_mod.SCOREABLE_HORIZONS)} "
                 f"days."),
        "benchmark": ("Every call is measured as excess return against SPY over the same window. A "
                      "call that said up in a week when the whole market rose is not credited with "
                      "the market's move."),
        "noise_floor": scoring.NOISE_FLOOR,
        "noise_floor_text": (f"A move inside plus or minus {scoring.NOISE_FLOOR:.0%} against the "
                             f"benchmark is recorded as inconclusive rather than counted either "
                             f"way. Counting small moves as hits is the easiest way to manufacture "
                             f"a track record."),
        # Disclosed here rather than only in docs/analysis/, because this is the page a reader
        # reaches from a published record. The noise floor is the control that is supposed to
        # absorb price noise, and on a thin symbol the FEED's own divergence can be larger than
        # it — so the reader is told where the floor stops working, beside the floor itself.
        "price_source": {
            "measured_divergence_pct": 0.391,
            "worst_symbol_divergence_pct": 2.86,
            "text": (f"Prices are end-of-day closes from a single free feed, which carries one "
                     f"exchange's prints rather than the consolidated tape. Measured 2026-09-14 "
                     f"against an independent feed over 961 day-pairs, closes differ by 0.391% on "
                     f"average — well inside the {scoring.NOISE_FLOOR:.0%} noise floor."),
            "limit": (f"That average hides a thin-name tail, and it is the honest limit of every "
                      f"verdict on this site. On the least liquid symbols measured, the two feeds "
                      f"disagreed by 2.86% and 2.29% on average — LARGER than the "
                      f"{scoring.NOISE_FLOOR:.0%} floor that exists to absorb exactly this. On a "
                      f"thinly traded symbol the choice of price feed can therefore move a call "
                      f"across the line by itself, and because a verdict is sealed and never "
                      f"revised, it stays moved. Liquid symbols are nowhere near this. Read a "
                      f"verdict on an illiquid name with that in mind."),
        },
        "verdicts": [
            {"key": "hit", "means": "the excess return moved past the noise floor in the "
                                    "direction the call named."},
            {"key": "miss", "means": "the excess return moved past the noise floor in the "
                                     "opposite direction."},
            {"key": "inconclusive", "means": "the move was inside the noise floor. The call was "
                                             "not evidence either way, and it is shown rather than "
                                             "dropped."},
            {"key": "unscoreable", "means": "there is no usable price series, so no honest verdict "
                                            "exists. The call is still published and still "
                                            "counted in the totals."},
        ],
        "sample_gate": SAMPLE_GATE,
        "sample_gate_text": GATE_REASON,
        "horizons": list(calls_mod.SCOREABLE_HORIZONS),
        "min_thesis_chars": calls_mod.MIN_THESIS_CHARS,
        "chain": {
            "algorithm": "sha256 over the previous hash followed by a canonical serialisation of "
                         "the sealed fields.",
            "sealed_fields": list(chain.SEALED_FIELDS),
            "proves": ("That the caller has not edited, deleted, reordered or backdated anything. "
                       "Every hash is recomputable by anyone from the fields shown on this site, "
                       "and one changed character breaks every link after it."),
            # Written as a complete sentence because it travels: the record page shows it under
            # the verification result, where there is no heading above it to lean on.
            "does_not_prove": ("The chain does not prove that WE have not rewritten it. We hold "
                               "every field, so this operator could edit a call and recompute the "
                               "whole chain after it. Making that impossible needs an anchor "
                               "outside our control, publishing the chain head daily somewhere we "
                               "cannot revise, and that is not built yet. This is not a blockchain "
                               "and we do not call it one."),
        },
    }


def scoreable_universe(conn: psycopg.Connection) -> dict:
    """How many symbols currently have a price series, and how fresh it is.

    The methodology page states the size of the scoreable universe, and a hardcoded number there
    would be wrong within a week.
    """
    with conn.cursor() as cur:
        cur.execute("""SELECT count(DISTINCT symbol), max(day),
                              max(day) FILTER (WHERE symbol = 'SPY')
                         FROM prices_eod""")
        symbols, newest, spy_newest = cur.fetchone()
        # Which feed is actually behind the most recent session, read from the rows themselves.
        # Naming the feed in prose would be a second copy of a fact that already lives in the
        # data, and the copy is the one that goes stale the day the source changes.
        cur.execute("""SELECT source, count(*) FROM prices_eod
                        WHERE day = (SELECT max(day) FROM prices_eod)
                        GROUP BY source ORDER BY count(*) DESC LIMIT 1""")
        row = cur.fetchone()
    return {"symbols": symbols or 0,
            "newest_close": newest.isoformat() if newest else None,
            "benchmark_newest_close": spy_newest.isoformat() if spy_newest else None,
            "price_feed": row[0] if row else None}
