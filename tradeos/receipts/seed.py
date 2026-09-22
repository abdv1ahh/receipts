"""Importing our own signal engine's record as the first two callers on the board.

NOTHING HERE IS INVENTED. There is exactly one honest source of historical record in this database
and it is the signal plane's own resolved claims: 473 of them, already scored, already measured
against SPY, already sitting in `claims` and `claim_outcomes`. This module reads those rows,
preserves their real timestamps and their real verdicts, and seals them into a chain. The chain is
computed over facts that were in the database before this feature existed.

WHY WE PUBLISH IT AT ALL, given what it says. Across the two versions the engine was right on
43.2% of the calls that resolved as a hit or a miss, which is BELOW a coin flip, and its expectancy
interval spans zero, so on this sample no edge is demonstrated in either direction. It would take
1,268 resolved calls to detect a 1% per call edge and there are 412. We put it on the board first,
labelled as ours, because a scoreboard that only shows winners is not a scoreboard, and because
asking other people to publish an unflattering record while hiding our own would be the fastest
possible way to deserve nobody's trust.

That figure must never be presented as a positive result anywhere in this product.

TWO CALLERS, NOT ONE. `convergence-v3` and `convergence-v4` are two version rows of the SAME
scoring logic: v4's own changelog in `signal_definitions` records "NO BEHAVIOURAL CHANGE", it was
re-registered after a lint pass moved the module hash. Splitting them here gives the board two real
rows with genuinely different sample sizes, which demonstrates the gate visually with real data
instead of a contrived example. Pooling them for the house figure is legitimate for the same reason
they are the same model; `record.house_summary` does that and says why.

WHAT AN IMPORTED CALL CANNOT SHOW. `claim_outcomes` stored the excess return and the entry day, not
the component prices, so the four price columns on an imported call are NULL and its proof panel
says so in as many words. Back-filling them now would mean recomputing a price lookup today and
presenting the result as what was measured then. Every other caller's calls carry the full
arithmetic; these carry what was actually recorded.
"""
from __future__ import annotations

import psycopg
from psycopg.types.json import Json

from .. import stats
from . import chain, context

# handle -> (display name, the model_version rows it imports, bio)
HOUSE_CALLERS = {
    "convergence-v3": (
        "Convergence v3",
        "convergence-v3",
        "Our own smart money convergence signal, version 3. It scores clusters of independent SEC "
        "filings on one issuer inside a short window, and it is on this board so that our record "
        "is as checkable as anybody else's.",
    ),
    "convergence-v4": (
        "Convergence v4",
        "convergence-v4",
        "The same scoring logic as version 3, re registered after a lint pass changed the module "
        "hash. Its own changelog records no behavioural change, so the difference between these "
        "two records is sample and period, not model.",
    ),
}


def _ensure_caller(conn: psycopg.Connection, handle: str) -> int:
    display_name, _model, bio = HOUSE_CALLERS[handle]
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM callers WHERE handle = %s", (handle,))
        row = cur.fetchone()
        if row:
            return row[0]
        # verification_method 'house' rather than a pretend public post. We are not proving we
        # control someone else's audience; we are stating that this record is ours.
        cur.execute("""INSERT INTO callers (handle, display_name, bio, kind, is_house,
                                            verified_at, verification_method,
                                            jurisdiction_attested)
                       VALUES (%s,%s,%s,'algorithm',true, now(), 'house', true)
                       RETURNING id""", (handle, display_name, bio))
        caller_id = cur.fetchone()[0]
    conn.commit()
    return caller_id


def _source_rows(conn: psycopg.Connection, model_version: str) -> list[tuple]:
    """Every resolved claim of one model version with its outcome, in true chronological order.

    Ordered by (created_at, claim id). Many of these share a timestamp to the second, so
    created_at alone is not a total order, and a chain built on a non deterministic order would
    verify today and fail after the next re-import.
    """
    with conn.cursor() as cur:
        cur.execute("""SELECT c.id, c.created_at, c.mechanism, c.confidence, c.horizon_days,
                              o.subject, o.predicted, o.verdict, o.excess_return,
                              o.entry_day, o.exit_day, o.note
                         FROM claims c JOIN claim_outcomes o ON o.claim_id = c.id
                        WHERE c.model_version = %s
                     ORDER BY c.created_at, c.id""", (model_version,))
        return cur.fetchall()


_IMPORT_NOTE = ("Imported from the signal engine's own ledger, where it was scored when its "
                "horizon closed. The excess return against SPY and the entry session are the "
                "figures that were recorded at the time. The component prices were not stored "
                "then, so they are shown as absent rather than recomputed today.")


def seed_house_records(conn: psycopg.Connection) -> dict:
    """Import both house records. Idempotent by refusal, not by overwrite.

    A caller that already holds calls is skipped entirely. There is no update path into an append
    only table, and a re-import that appended a second copy of the same 323 calls would double the
    record, which is precisely the kind of quiet corruption this product exists to make impossible.
    """
    totals: dict[str, dict] = {}

    for handle, (_name, model_version, _bio) in HOUSE_CALLERS.items():
        caller_id = _ensure_caller(conn, handle)
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM calls WHERE caller_id = %s", (caller_id,))
            existing = cur.fetchone()[0]
        if existing:
            totals[handle] = {"skipped": True, "existing_calls": existing,
                              "note": "already imported; an append only record is never imported twice."}
            continue

        rows = _source_rows(conn, model_version)
        prev = chain.GENESIS_HASH
        counts = {"hit": 0, "miss": 0, "inconclusive": 0, "unscoreable": 0}

        with conn.cursor() as cur:
            for seq, r in enumerate(rows, start=1):
                (_claim_id, created_at, mechanism, confidence, horizon_days, subject, predicted,
                 verdict, excess, entry_day, exit_day, note) = r

                sealed = {
                    "caller_id": caller_id, "seq": seq,
                    "symbol": (subject or "").upper(),
                    "direction": predicted,
                    "horizon_days": horizon_days,
                    # The stored confidence is a probability; the record's vocabulary is three
                    # buckets. `stats.confidence_bucket` is the one mapping between them, so
                    # calibration on this record means the same thing as calibration on the Ledger.
                    "confidence": stats.confidence_bucket(float(confidence)),
                    "thesis": mechanism,
                    "benchmark_symbol": "SPY",
                    "published_at": created_at,
                    "knowable_time": created_at,
                }
                _payload, digest = chain.seal(sealed, prev)
                counts[verdict] = counts.get(verdict, 0) + 1

                cur.execute(
                    """INSERT INTO calls (caller_id, seq, symbol, direction, horizon_days,
                                          confidence, thesis, benchmark_symbol, published_at,
                                          knowable_time, prev_hash, content_hash, entry_session,
                                          exit_session, excess_return, verdict, verdict_note,
                                          resolved_at, context_snapshot)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (caller_id, seq, sealed["symbol"], predicted, horizon_days,
                     sealed["confidence"], mechanism, "SPY", created_at, created_at, prev, digest,
                     entry_day, exit_day, excess, verdict,
                     f"{note}. {_IMPORT_NOTE}" if note else _IMPORT_NOTE,
                     created_at,
                     Json(context.empty(created_at,
                                        "this call predates the frozen context mechanism; it was "
                                        "imported from the signal engine's ledger."))))
                prev = digest
        conn.commit()
        totals[handle] = {"caller_id": caller_id, "imported": len(rows), "chain_head": prev,
                          **counts}

    return totals
