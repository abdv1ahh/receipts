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

import json
import pathlib
from datetime import UTC, date, datetime

import psycopg
from psycopg.types.json import Json

from .. import stats
from . import chain, context

# The committed export, which is the ONLY copy of this record that ships with the repository.
# `claims`/`claim_outcomes` belong to the signal plane, which was deleted in the extraction: the
# tables are still in the schema, they ship empty, and nothing here can refill them. So on every
# machine that is not the operator's, this directory is the source.
EXPORT_DIR = pathlib.Path(__file__).resolve().parents[2] / "export"

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


def _ensure_caller(conn: psycopg.Connection, handle: str, pin_id: int | None = None) -> int:
    """The house caller, created if absent.

    `pin_id` EXISTS BECAUSE `caller_id` IS A SEALED FIELD. It is the first of the ten, so the whole
    chain hangs off it: restoring these calls under a fresh serial id recomputes every hash and
    produces a record that verifies perfectly and does not match the published head. Anyone
    checking the export against a self-hosted board would get two different answers and no way to
    tell which was lying. So a restore takes the id the chain was sealed with, and the sequence is
    moved past it so the next caller cannot collide.
    """
    display_name, _model, bio = HOUSE_CALLERS[handle]
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM callers WHERE handle = %s", (handle,))
        row = cur.fetchone()
        if row:
            return row[0]
        if pin_id is not None:
            cur.execute("""INSERT INTO callers (id, handle, display_name, bio, kind, is_house,
                                                verified_at, verification_method,
                                                jurisdiction_attested)
                           VALUES (%s,%s,%s,%s,'algorithm',true, now(), 'house', true)
                           RETURNING id""", (pin_id, handle, display_name, bio))
            caller_id = cur.fetchone()[0]
            cur.execute("""SELECT setval(pg_get_serial_sequence('callers','id'),
                                  GREATEST((SELECT max(id) FROM callers), %s))""", (pin_id,))
            conn.commit()
            return caller_id
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
        # ASKED FIRST, because these two tables are not merely empty off the operator's machine —
        # they are ABSENT. They were the signal plane's, the plane was deleted in the extraction,
        # and `migrations/baseline/` (what every fresh install gets) never creates them. Querying
        # them raised UndefinedTable and took the whole command down before the export fallback
        # below could run.
        cur.execute("SELECT to_regclass('claims'), to_regclass('claim_outcomes')")
        if any(t is None for t in cur.fetchone()):
            return []
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


def _export_doc(handle: str) -> dict | None:
    """The committed export for one handle, or None if it is absent or empty."""
    path = EXPORT_DIR / f"{handle}.json"
    if not path.is_file():
        return None
    doc = json.loads(path.read_text(encoding="utf-8"))
    return doc if doc.get("links") else None


def _ts(text: str) -> datetime:
    """A sealed timestamp back from its canonical spelling. `chain._render` writes
    `%Y-%m-%dT%H:%M:%S.%fZ`; anything else did not come out of this product."""
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)


_RESTORE_NOTE = ("Restored from the committed export of this record, which carries the sealed "
                 "fields, the two hashes and the outcome that was measured when the horizon "
                 "closed. The component prices were never part of the export and are absent "
                 "rather than recomputed today.")


def _import_from_export(conn: psycopg.Connection, handle: str, doc: dict) -> dict:
    """Rebuild one house record from its export, reproducing the published head exactly.

    The values are sealed BACK FROM THE EXPORTED TEXT rather than from re-rendered database types.
    `chain._render` passes a string through untouched, so text in gives byte-identical payloads —
    and the alternative, parsing each value and trusting the round trip to re-render identically,
    is exactly the class of bug the microsecond-and-trailing-Z rule exists to prevent.

    Every link is checked against its exported `content_hash` as it is sealed, and the final head
    against the exported head. A restore that does not reproduce the published head is refused
    outright: a house record that disagrees with its own published hash is worse than no house
    record, because the whole board is an argument that the hash is the thing you can trust.
    """
    sealed_caller = int(doc["links"][0]["values"]["caller_id"])
    caller_id = _ensure_caller(conn, handle, pin_id=sealed_caller)
    if caller_id != sealed_caller:
        return {"sealed": 0, "source": "export", "refused": True,
                "reason": f"@{handle} already exists as caller {caller_id}, but this record was "
                          f"sealed under caller {sealed_caller} and `caller_id` is the first of "
                          f"the ten sealed fields. Restoring it here would recompute every hash "
                          f"and produce a record whose head does not match the published "
                          f"{doc['head'][:16]}. Nothing was written."}

    by_seq = {o["seq"]: o for o in doc.get("outcomes", [])}
    counts = {"hit": 0, "miss": 0, "inconclusive": 0, "unscoreable": 0}
    prev, open_calls = chain.GENESIS_HASH, 0

    with conn.cursor() as cur:
        for link in sorted(doc["links"], key=lambda x: x["seq"]):
            v = link["values"]
            _payload, digest = chain.seal(v, prev)
            if digest != link["content_hash"]:
                conn.rollback()
                return {"sealed": 0, "source": "export", "refused": True,
                        "reason": f"@{handle} link {link['seq']} does not reseal to its exported "
                                  f"hash. The export is damaged; nothing was written."}
            o = by_seq.get(link["seq"], {})
            verdict = o.get("verdict")
            if verdict in counts:
                counts[verdict] += 1
            elif verdict is None:
                open_calls += 1
            note = o.get("verdict_note")
            published = _ts(v["published_at"])
            cur.execute(
                """INSERT INTO calls (caller_id, seq, symbol, direction, horizon_days, confidence,
                                      thesis, benchmark_symbol, published_at, knowable_time,
                                      prev_hash, content_hash, entry_session, exit_session,
                                      excess_return, verdict, verdict_note, resolved_at,
                                      open_reason_code, open_reason, context_snapshot)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (caller_id, int(v["seq"]), v["symbol"], v["direction"], int(v["horizon_days"]),
                 v["confidence"], v["thesis"], v["benchmark_symbol"], published,
                 _ts(v["knowable_time"]), prev, digest,
                 date.fromisoformat(o["entry_session"]) if o.get("entry_session") else None,
                 date.fromisoformat(o["exit_session"]) if o.get("exit_session") else None,
                 o.get("excess_return"), verdict,
                 f"{note} {_RESTORE_NOTE}" if note else (_RESTORE_NOTE if verdict else None),
                 datetime.fromisoformat(o["resolved_at"]) if o.get("resolved_at") else None,
                 o.get("open_reason_code"), o.get("open_reason"),
                 Json(context.empty(published,
                                    "this call predates the frozen context mechanism; it was "
                                    "restored from this record's committed export."))))
            prev = digest

    if prev != doc["head"]:
        conn.rollback()
        return {"sealed": 0, "source": "export", "refused": True,
                "reason": f"@{handle} rebuilt to head {prev[:16]}, but the export publishes "
                          f"{doc['head'][:16]}. Nothing was written."}
    conn.commit()
    return {"caller_id": caller_id, "sealed": len(doc["links"]), "source": "export",
            "chain_head": prev, "open": open_calls, **counts}


def seed_house_records(conn: psycopg.Connection) -> dict:
    """Import both house records. Idempotent by refusal, not by overwrite.

    A caller that already holds calls is skipped entirely. There is no update path into an append
    only table, and a re-import that appended a second copy of the same 323 calls would double the
    record, which is precisely the kind of quiet corruption this product exists to make impossible.
    """
    totals: dict[str, dict] = {}

    for handle, (_name, model_version, _bio) in HOUSE_CALLERS.items():
        with conn.cursor() as cur:
            cur.execute("""SELECT c.id, (SELECT count(*) FROM calls WHERE caller_id = c.id)
                             FROM callers c WHERE c.handle = %s""", (handle,))
            row = cur.fetchone()
        if row and row[1]:
            totals[handle] = {"skipped": True, "existing_calls": row[1],
                              "note": "already imported; an append only record is never imported twice."}
            continue

        # TWO SOURCES, AND THE ORDER IS NOT A PREFERENCE. `claims` is the operator's own ledger and
        # is authoritative where it exists. Everywhere else it is an empty table left behind by the
        # deleted signal plane, and reading it produced the failure this path was written to fix: a
        # run that sealed nothing, printed `0 calls sealed ... chain head 0000000000000000` and
        # exited 0 — a success report for having done nothing, which is the exact shape of failure
        # the scheduler's zero-output alarm exists to catch.
        rows = _source_rows(conn, model_version)
        if not rows:
            doc = _export_doc(handle)
            if doc is None:
                totals[handle] = {
                    "sealed": 0, "source": None,
                    "reason": f"nothing to import for @{handle}: no resolved row for model "
                              f"version {model_version} in `claims` (that table belonged to the "
                              f"retired signal plane, and a fresh install does not create it at "
                              f"all), and no committed export at "
                              f"{EXPORT_DIR / (handle + '.json')}."}
                continue
            totals[handle] = _import_from_export(conn, handle, doc)
            continue

        caller_id = _ensure_caller(conn, handle)
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
        totals[handle] = {"caller_id": caller_id, "sealed": len(rows), "source": "claims",
                          "chain_head": prev, "open": 0, **counts}

    return totals
