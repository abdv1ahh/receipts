"""The pure-insider signal's DATABASE path, and that the analysis replica agrees with it.

Why this file exists at all: `scripts/analysis/compute_v5.py` does not call
`insider.gather_events`. It loads every purchase once and replays in memory, because the DB path
issues two queries per issuer per day and the analysis replays 3,645 issuers. That makes
`insider.py`'s gather the *canonical* definition of what this signal reads and the analysis a
*replica* of it — and an unexercised canonical path is how the two quietly stop agreeing
(CLAUDE.md §0b2, the `pct` formatter that drifted across four files).

So these tests do two jobs: they run the canonical path against a real database, and they assert
the replica selects the same transactions with the same labels. It is the same discipline
`compute_v5.LiquidityFloor` applies to itself by re-checking against the real SQL every run.

Read-only — nothing is inserted, so there is nothing to tear down. Skips cleanly with no database,
like `test_receipts.py`.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

import pytest

try:
    from tradeos import db
    from tradeos.signals import convergence, insider, opportunistic
    _IMPORTS_OK = True
except Exception:                                             # pragma: no cover
    _IMPORTS_OK = False


def _db_reachable() -> bool:
    if not _IMPORTS_OK:
        return False
    try:
        with db.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT to_regclass('insider_transactions')")
            return cur.fetchone()[0] is not None
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _db_reachable(), reason="no database reachable; the insider-signal gather needs one")

PARAMS = insider.DEFAULT_PARAMS


def _busy_issuer_and_day(cur):
    """An (issuer, as_of) with enough purchases in the window to exercise the gate both ways."""
    cur.execute(
        """SELECT issuer_entity, max(knowable_time) FROM insider_transactions
           WHERE issuer_entity IS NOT NULL
             AND transaction_code = 'P' AND acquired_disposed = 'A'
           GROUP BY issuer_entity
           HAVING count(DISTINCT owner_cik) >= 3
           ORDER BY count(*) DESC LIMIT 1""")
    row = cur.fetchone()
    if row is None:
        pytest.skip("no issuer with three distinct insider buyers in this database")
    issuer, latest = row
    return issuer, latest.replace(hour=23, minute=59, second=59)


def test_gather_reads_only_open_market_purchases():
    """Code P acquired, and nothing else: no sales, option exercises, grants or tax withholding.

    Jeng, Metrick & Zeckhauser: purchases carry signal, sales do not. `convergence` expressed that
    by scoring sales at weight 0 and keeping them as context; this signal expresses it by never
    selecting them, so a sale cannot appear as a voice even by accident.
    """
    with db.connect() as conn, conn.cursor() as cur:
        issuer, as_of = _busy_issuer_and_day(cur)
        events, counts = insider.gather_events(conn, issuer, as_of, PARAMS)
        assert events, "expected at least one purchase for the busiest issuer"
        assert {e.subtype for e in events} == {"insider_purchase"}
        assert {e.ref["code"] for e in events} == {"P"}

        ids = sorted({e.ref["id"] for e in events})
        cur.execute(
            """SELECT count(*) FROM insider_transactions
               WHERE id = ANY(%s) AND NOT (transaction_code = 'P' AND acquired_disposed = 'A')""",
            (ids,))
        assert cur.fetchone()[0] == 0, "a non-purchase reached the event list"
        assert sum(counts.values()) == len(events) + counts[opportunistic.ROUTINE]


def test_gather_never_reads_a_filing_that_was_not_yet_public():
    """Point-in-time discipline: every contributing event must be knowable at as_of.

    Asserted against the database rather than against the pure scorer, because the scorer's
    look-ahead guard cannot save a gather that selected the wrong rows in the first place.
    """
    with db.connect() as conn, conn.cursor() as cur:
        issuer, as_of = _busy_issuer_and_day(cur)
        for offset in (0, 30, 200):
            when = as_of - timedelta(days=offset)
            events, _ = insider.gather_events(conn, issuer, when, PARAMS)
            for e in events:
                assert e.knowable_time <= when, f"{e.ref['id']} was not public at {when}"
                assert e.knowable_time > when - timedelta(days=PARAMS["window_days"])


def test_routine_insiders_are_neither_a_voice_nor_a_contribution():
    """CMP's whole finding is the split, so a routine trade must not reach the score by any route.

    Counted but not emitted: `counts` still reports it, because a filter that silently drops rows
    is indistinguishable from a filter that is broken.
    """
    with db.connect() as conn, conn.cursor() as cur:
        issuer, as_of = _busy_issuer_and_day(cur)
        events, counts = insider.gather_events(conn, issuer, as_of, PARAMS)
        assert opportunistic.ROUTINE not in {e.ref["classification"] for e in events}
        assert set(counts) == {opportunistic.ROUTINE, opportunistic.OPPORTUNISTIC,
                               opportunistic.UNCLASSIFIED}


def test_the_analysis_replica_gathers_the_same_events_as_the_database_path():
    """`compute_v5.py` replays in memory for speed. It must agree with the canonical gather.

    Compared on which transactions were selected and what label each was given, which is
    everything the score is computed from. A divergence here would mean the published measurement
    describes a signal the module does not implement.
    """
    with db.connect() as conn, conn.cursor() as cur:
        issuer, as_of = _busy_issuer_and_day(cur)
        canonical, _ = insider.gather_events(conn, issuer, as_of, PARAMS)

        # The replica, exactly as compute_v5.load_purchases does it: classify each purchase once,
        # against history visible at that purchase's own knowable_time, keyed on issuer_cik.
        window_start = as_of - timedelta(days=PARAMS["window_days"])
        cur.execute(
            """SELECT id, owner_cik, issuer_cik, knowable_time, event_time
               FROM insider_transactions
               WHERE issuer_entity = %s AND transaction_code = 'P' AND acquired_disposed = 'A'
                 AND knowable_time <= %s AND knowable_time > %s""",
            (issuer, as_of, window_start))
        purchases = cur.fetchall()
        cur.execute(
            """SELECT issuer_cik, owner_cik, event_time, knowable_time
               FROM insider_transactions WHERE issuer_cik = ANY(%s)""",
            (sorted({p[2] for p in purchases}),))
        history: dict[tuple[str, str], list] = defaultdict(list)
        for issuer_cik, owner, event_time, knowable in cur.fetchall():
            history[(issuer_cik, owner)].append((event_time, knowable))

        replica = {}
        for tid, owner, issuer_cik, knowable, event_time in purchases:
            visible = [e for e, k in history[(issuer_cik, owner)] if k <= knowable]
            label = opportunistic.classify_insider(visible, event_time)
            if opportunistic.counts_toward_gate(label):
                replica[tid] = label

    assert {e.ref["id"]: e.ref["classification"] for e in canonical} == replica


def test_the_gate_is_one_source_class_and_two_voices():
    """The point of the exercise. `convergence`'s min_source_classes:2 makes a pure-insider
    cluster unreachable; this definition's 1 is what allows the test to exist at all."""
    assert PARAMS["gate"] == {"min_source_classes": 1, "min_voices": 2}
    assert PARAMS["transaction_codes"] == ["P"]
    with db.connect() as conn, conn.cursor() as cur:
        issuer, as_of = _busy_issuer_and_day(cur)
        result, _ = insider.compute_for_issuer(conn, issuer, as_of, PARAMS)
        assert result.source_classes == ["insider"]
        assert result.passes_gate == (result.voices >= 2)


def test_the_liquidity_floor_is_convergence_v3s_own_and_not_a_second_copy():
    """A second definition of "liquid enough" would make the v3 comparison meaningless."""
    assert PARAMS["liquidity_floor_usd"] == convergence.DEFAULT_PARAMS["liquidity_floor_usd"]
    assert PARAMS["liquidity_window_days"] == convergence.DEFAULT_PARAMS["liquidity_window_days"]
    assert PARAMS["buckets"] == convergence.DEFAULT_PARAMS["buckets"]
    with db.connect() as conn, conn.cursor() as cur:
        issuer, as_of = _busy_issuer_and_day(cur)
        assert (insider.passes_liquidity_floor(conn, issuer, as_of, PARAMS)
                is convergence.passes_liquidity_floor(conn, issuer, as_of, PARAMS))


def test_candidate_issuers_only_offers_issuers_with_a_purchase_in_the_window():
    with db.connect() as conn, conn.cursor() as cur:
        _issuer, as_of = _busy_issuer_and_day(cur)
        issuers = insider.candidate_issuers(conn, as_of, PARAMS)
        assert issuers, "expected candidates on the busiest day"
        window_start = as_of - timedelta(days=PARAMS["window_days"])
        cur.execute(
            """SELECT count(DISTINCT issuer_entity) FROM insider_transactions
               WHERE transaction_code = 'P' AND acquired_disposed = 'A'
                 AND knowable_time <= %s AND knowable_time > %s AND issuer_entity IS NOT NULL""",
            (as_of, window_start))
        assert cur.fetchone()[0] == len(issuers)


def test_the_hash_guard_watches_every_file_that_can_change_the_meaning():
    """Hashing only the thin wrapper would let an edit to the scorer or the classifier pass the
    version guard unnoticed, which is the exact failure decision #24 exists to prevent."""
    import hashlib
    from pathlib import Path

    assert set(insider._HASHED_SOURCES) == {"insider.py", "opportunistic.py", "convergence.py"}
    here = Path(insider.__file__).parent
    h = hashlib.sha256()
    for name in insider._HASHED_SOURCES:
        h.update(name.encode())
        h.update((here / name).read_bytes())
    assert h.hexdigest() == insider.module_code_hash()
    assert insider.module_code_hash() != convergence.module_code_hash()


def test_it_is_not_registered_as_a_convergence_version():
    """A definition numbered 5 under ANY name would restamp live claims `convergence-v5` through
    `smartmoney_claims`, and those claims are sealed into Receipts permanently."""
    assert insider.NAME != convergence.NAME
    with db.connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT max(version) FROM signal_definitions WHERE name = %s",
                    (convergence.NAME,))
        assert cur.fetchone()[0] == 4, "convergence has gained a version; check what stamped it"
        cur.execute("SELECT max(version) FROM signal_definitions")
        assert cur.fetchone()[0] == 4, (
            "max(version) across all names has moved past 4; smartmoney_claims used to read this "
            "and the scheduler stamps live claims with it")


def test_convergence_is_untouched_so_v3_and_v4_stay_recomputable():
    """The whole comparison rests on v3 and v4 meaning today what they meant when computed."""
    with db.connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT code_hash FROM signal_definitions WHERE name = %s AND version = 4",
                    (convergence.NAME,))
        registered = cur.fetchone()
        if registered is None:
            pytest.skip("convergence v4 is not registered in this database")
        assert registered[0] == convergence.module_code_hash(), (
            "convergence.py has changed; v3 and v4 can no longer be recomputed from this commit")


def test_no_insider_clusters_were_written_to_the_shared_table():
    """`signal_clusters` has no definition filter at any of its 30 read sites, so a stored
    pure-insider definition would double-count the Smart Money feed and the public calibration."""
    with db.connect() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT count(*) FROM signal_clusters c JOIN signal_definitions d
                 ON d.id = c.definition_id WHERE d.name = %s""", (insider.NAME,))
        assert cur.fetchone()[0] == 0
        cur.execute("""SELECT count(*) FROM (
                         SELECT issuer_entity, as_of FROM signal_clusters
                         GROUP BY 1, 2 HAVING count(DISTINCT definition_id) > 1) t""")
        assert cur.fetchone()[0] == 0, (
            "two definitions now share an (issuer, as_of); the clusters feed will double-count")


def test_the_replay_as_of_matches_the_daily_convention():
    """`compute_daily` stamps 23:59:59 UTC on a business day, and the analysis replays the same
    instant, so a v5 as_of and a v3 as_of mean the same moment.

    NOT every stored cluster carries that stamp, and asserting it did is how this test first
    failed. `compute-signals` without `--daily` calls `compute_and_store` with a parsed or
    current timestamp, so v3 also holds 449 clusters at 10:46, 14:32 and 15:31, and v4 holds
    146 at 01:13. Those are ad-hoc runs, not replay points. What matters for a comparison is
    that the DAILY replay convention is one instant, and it is: 16,696 v3 clusters over 416
    days and 378 v4 clusters over 76 days all sit at 23:59:59, and the two version's day sets
    are disjoint — which is the only reason the clusters feed does not already double-count.
    """
    import inspect

    from tradeos.signals import definitions
    src = inspect.getsource(definitions.compute_daily)
    assert "23, 59, 59" in src and "tzinfo=UTC" in src, "the daily replay instant moved"

    with db.connect() as conn, conn.cursor() as cur:
        cur.execute("""SELECT count(*) FROM signal_clusters
                       WHERE as_of::time = '23:59:59'""")
        daily = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM signal_clusters")
        assert daily > 0.9 * cur.fetchone()[0], "most clusters should come from a daily replay"
