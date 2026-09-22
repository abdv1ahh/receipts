"""Receipts: the integrity guarantees, publishing, scoring and the sample gate.

The append-only tests in here are the evidence behind the product's central claim. Everything else
Receipts says about itself follows from three refusals actually firing in a real database, so they
are tested against one rather than against a mock. Like `test_authz_adversarial.py`, this file
skips cleanly where no database is reachable.

Everything it creates is removed in teardown. Removing it requires disabling the trigger, which is
the operator hole the methodology page discloses in as many words: we can rewrite this table and
nobody outside could tell. That is stated rather than hidden, and closing it needs an anchor
outside our control.
"""
from __future__ import annotations

import decimal
import secrets
from datetime import UTC, date, datetime, timedelta

import pytest

try:
    import psycopg

    from tradeos import db
    from tradeos.backtest.engine import Series
    from tradeos.receipts import calls, chain, record, scoring, verification
    _IMPORTS_OK = True
except Exception:                                             # pragma: no cover
    _IMPORTS_OK = False


def _db_reachable() -> bool:
    if not _IMPORTS_OK:
        return False
    try:
        with db.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT to_regclass('calls')")
            return cur.fetchone()[0] is not None
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _db_reachable(),
                                reason="no database reachable; the Receipts integrity tests need one")

VALID = {"symbol": "ABT", "direction": "up", "horizon_days": 30, "confidence": "medium",
         "thesis": "a thesis with more than forty characters in it, so a reader can judge it"}


@pytest.fixture
def caller():
    """A scratch caller, removed afterwards along with everything it published."""
    handle = f"test-{secrets.token_hex(6)}"
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO callers (handle, display_name, kind, jurisdiction_attested)
                           VALUES (%s, %s, 'human', true) RETURNING id""", (handle, "Test Caller"))
            caller_id = cur.fetchone()[0]
        conn.commit()
        yield caller_id, handle, conn
        # Roll back FIRST. A test that fails inside a cursor leaves the transaction aborted, and
        # every statement below then errors with "current transaction is aborted" — so the teardown
        # silently does nothing and the scratch caller is left on the public board. That happened:
        # six of them accumulated before this line existed.
        conn.rollback()
        with conn.cursor() as cur:
            # The trigger refuses this, which is the point of it. An operator can switch it off;
            # nobody else can, and the methodology page says so.
            cur.execute("ALTER TABLE calls DISABLE TRIGGER calls_append_only_trg")
            cur.execute("DELETE FROM calls WHERE caller_id = %s", (caller_id,))
            cur.execute("ALTER TABLE calls ENABLE TRIGGER calls_append_only_trg")
            cur.execute("DELETE FROM caller_verifications WHERE caller_id = %s", (caller_id,))
            cur.execute("DELETE FROM callers WHERE id = %s", (caller_id,))
        conn.commit()


# ================================================================== THE APPEND-ONLY GUARANTEE
#
# Three refusals. If any of these stops firing, this product is a marketing page with a database
# behind it, so they are named for what they protect rather than for the SQL they run.

def test_a_published_call_can_never_be_deleted(caller):
    caller_id, _handle, conn = caller
    published = calls.publish(caller_id, VALID, conn)
    with pytest.raises(psycopg.errors.RaiseException) as exc:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM calls WHERE id = %s", (published["id"],))
    conn.rollback()
    assert "append only" in str(exc.value)

    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM calls WHERE id = %s", (published["id"],))
        assert cur.fetchone()[0] == 1


@pytest.mark.parametrize("column, value", [
    ("thesis", "a quietly better thesis, written once the answer was known, forty plus chars"),
    ("symbol", "MSFT"),
    ("direction", "down"),
    ("horizon_days", 90),
    ("confidence", "high"),
    ("published_at", datetime(2020, 1, 1, tzinfo=UTC)),
    ("knowable_time", datetime(2020, 1, 1, tzinfo=UTC)),
    ("prev_hash", "f" * 64),
    ("content_hash", "e" * 64),
    ("benchmark_symbol", "QQQ"),
    ("seq", 99),
])
def test_no_sealed_column_can_be_rewritten(caller, column, value):
    """Every column the hash is computed over, one at a time. A gap here is a field a caller could
    edit while the chain still verified, because the chain would be recomputed over the edit."""
    caller_id, _handle, conn = caller
    published = calls.publish(caller_id, VALID, conn)
    with pytest.raises(psycopg.errors.RaiseException) as exc:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE calls SET {column} = %s WHERE id = %s",   # noqa: S608 — literal
                        (value, published["id"]))
    conn.rollback()
    assert "sealed columns" in str(exc.value)


def test_a_resolved_verdict_can_never_be_changed(caller):
    """A miss that can become a hit later is not a record. Note this also binds US: a correction to
    the scorer cannot silently repaint history, it has to be disclosed."""
    caller_id, _handle, conn = caller
    published = calls.publish(caller_id, VALID, conn)
    with conn.cursor() as cur:
        cur.execute("""UPDATE calls SET verdict = 'miss', verdict_note = 'n', resolved_at = now()
                        WHERE id = %s""", (published["id"],))
    conn.commit()

    with pytest.raises(psycopg.errors.RaiseException) as exc:
        with conn.cursor() as cur:
            cur.execute("UPDATE calls SET verdict = 'hit' WHERE id = %s", (published["id"],))
    conn.rollback()
    assert "immutable" in str(exc.value)


def test_the_resolution_columns_stay_writable(caller):
    """The boundary has to be in the right place. Sealing everything would mean nothing could ever
    be scored, which would be a different way of having no record."""
    caller_id, _handle, conn = caller
    published = calls.publish(caller_id, VALID, conn)
    with conn.cursor() as cur:
        cur.execute("""UPDATE calls SET entry_price = 100, exit_price = 110, excess_return = 0.05,
                                        verdict = 'hit', verdict_note = 'scored', resolved_at = now()
                        WHERE id = %s""", (published["id"],))
    conn.commit()
    assert calls.get(published["id"], conn)["verdict"] == "hit"


def test_a_caller_who_has_published_cannot_be_deleted(caller):
    """No delete path at the other end either. Without this, deleting the caller would take the
    record with it and the append-only table would be trivially emptiable."""
    caller_id, _handle, conn = caller
    calls.publish(caller_id, VALID, conn)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with conn.cursor() as cur:
            cur.execute("DELETE FROM callers WHERE id = %s", (caller_id,))
    conn.rollback()


# ================================================================== publishing

def test_publishing_chains_each_call_to_the_one_before(caller):
    caller_id, _handle, conn = caller
    first = calls.publish(caller_id, VALID, conn)
    second = calls.publish(caller_id, {**VALID, "direction": "down"}, conn)

    assert first["seq"] == 1 and first["prev_hash"] == chain.GENESIS_HASH
    assert second["seq"] == 2 and second["prev_hash"] == first["content_hash"]
    result = chain.verify_chain(calls.for_chain(caller_id, conn))
    assert result["intact"] is True and result["links"] == 2


def test_a_published_call_verifies_against_its_own_stored_fields(caller):
    """The seal has to be reproducible from what is stored, not only from what was in memory at
    publish time. A rounding difference between the two would make every record unverifiable."""
    caller_id, _handle, conn = caller
    calls.publish(caller_id, VALID, conn)
    assert chain.verify_chain(calls.for_chain(caller_id, conn))["intact"] is True


def test_published_at_and_knowable_time_are_the_same_instant(caller):
    caller_id, _handle, conn = caller
    published = calls.publish(caller_id, VALID, conn)
    assert published["published_at"] == published["knowable_time"]


def test_an_invalid_call_is_refused_with_every_problem_at_once(caller):
    caller_id, _handle, conn = caller
    with pytest.raises(calls.PublishError) as exc:
        calls.publish(caller_id, {"symbol": "", "direction": "sideways", "horizon_days": 45,
                                  "confidence": "certain", "thesis": "up"}, conn)
    assert len(exc.value.problems) == 5


def test_an_unknown_symbol_is_published_and_sealed_unscoreable(caller):
    """Never silently rejected and never silently accepted as if it were scoreable. The record
    stays complete and the row says why it cannot be scored."""
    caller_id, _handle, conn = caller
    published = calls.publish(caller_id, {**VALID, "symbol": "ZZZZQQ"}, conn)
    assert published["verdict"] == "unscoreable"
    assert "no price series" in published["verdict_note"]
    assert chain.verify_chain(calls.for_chain(caller_id, conn))["intact"] is True


def test_a_stale_feed_publishes_open_rather_than_permanently_unscoreable(caller, monkeypatch):
    """The distinction the append-only trigger makes load bearing.

    A symbol whose feed is behind is scoreable; our data is late. Sealing it unscoreable would be
    permanent and wrong the moment the top-up catches up, and there would be no way to correct it.
    """
    caller_id, _handle, conn = caller
    monkeypatch.setattr(calls, "STALE_TOLERANCE_DAYS", -10_000)     # force every symbol to be stale
    published = calls.publish(caller_id, VALID, conn)
    assert published["verdict"] is None
    assert published["scoreability"]["scoreable"] is False
    assert published["scoreability"]["permanent"] is False


def test_a_publish_freezes_the_world_context(caller):
    caller_id, _handle, conn = caller
    published = calls.publish(caller_id, VALID, conn)
    snapshot = published["context_snapshot"]
    assert snapshot is not None
    assert "n_live" in snapshot and "alignment" in snapshot


# ================================================================== scoring

def test_entry_is_the_session_after_publication_never_the_one_in_progress(caller):
    """The single easiest way to flatter a record is to enter at the close of the day the call was
    made, when most of that move has already happened."""
    caller_id, _handle, conn = caller
    published_at = datetime.now(UTC) - timedelta(days=200)
    published = calls.publish(caller_id, VALID, conn, now=published_at)
    scoring.resolve_call(published["id"], conn)
    row = calls.get(published["id"], conn)
    assert row["entry_session"] > published_at.date().isoformat()


def test_the_stored_arithmetic_reconciles(caller):
    """The components have to actually produce the stored excess return.

    READ FROM THE DATABASE, not from `calls.get`. The six component columns are no longer in any
    payload — a market-data vendor's closes may not be redistributed and every surface here is a
    surface — so the assertion has to go to where they still live. That is the point of keeping
    them: a verdict nobody can see the components of is a verdict the operator cannot answer a
    challenge to, and this test is the operator making that check.
    """
    caller_id, _handle, conn = caller
    published = calls.publish(caller_id, VALID, conn, now=datetime.now(UTC) - timedelta(days=200))
    scoring.resolve_call(published["id"], conn)

    with conn.cursor() as cur:
        cur.execute("""SELECT entry_price, exit_price, benchmark_entry, benchmark_exit,
                              subject_return, benchmark_return, excess_return, verdict
                         FROM calls WHERE id = %s""", (published["id"],))
        e_in, e_out, b_in, b_out, sub, bench, excess, verdict = (
            float(v) if isinstance(v, decimal.Decimal) else v for v in cur.fetchone())

    assert verdict in ("hit", "miss", "inconclusive")
    assert sub == pytest.approx(e_out / e_in - 1, abs=1e-6)
    assert bench == pytest.approx(b_out / b_in - 1, abs=1e-6)
    assert excess == pytest.approx(sub - bench, abs=1e-5)


def test_the_components_that_arithmetic_used_never_reach_the_payload(caller):
    """The same call, from the reader's side. The numbers above are real, stored and sealed; none
    of them may be served. `tests/test_price_redistribution.py` sweeps the whole app for this —
    here it is pinned at the one function every Receipts surface reads its calls through."""
    caller_id, _handle, conn = caller
    published = calls.publish(caller_id, VALID, conn, now=datetime.now(UTC) - timedelta(days=200))
    scoring.resolve_call(published["id"], conn)
    r = calls.get(published["id"], conn)

    for column in ("entry_price", "exit_price", "benchmark_entry", "benchmark_exit",
                   "subject_return", "benchmark_return"):
        assert column not in r, f"{column} is the vendor's data and left the database"
    # And what replaces them, which has to survive or the verdict becomes unverifiable.
    assert r["entry_session"] and r["exit_session"] and r["excess_return"] is not None


def test_a_move_inside_the_noise_floor_is_inconclusive_not_a_hit():
    assert scoring.NOISE_FLOOR == 0.02
    verdict, reason = scoring.verdict_for("up", 0.019)
    assert verdict == "inconclusive" and "noise floor" in reason
    verdict, _ = scoring.verdict_for("up", 0.021)
    assert verdict == "hit"
    verdict, _ = scoring.verdict_for("up", -0.021)
    assert verdict == "miss"
    verdict, _ = scoring.verdict_for("down", -0.021)
    assert verdict == "hit"


def test_every_verdict_carries_a_reason_a_reader_can_check():
    """A bare 'miss' with no arithmetic beside it is exactly what a sceptic should distrust."""
    for direction, excess in (("up", 0.08), ("up", -0.08), ("down", 0.08), ("up", 0.001)):
        _verdict, reason = scoring.verdict_for(direction, excess)
        assert reason and len(reason) > 20


def test_resolving_writes_only_resolution_columns(caller):
    """If the scorer ever touched a sealed column the database would refuse it, which is why both
    the trigger and this test exist rather than only one of them."""
    caller_id, _handle, conn = caller
    published = calls.publish(caller_id, VALID, conn, now=datetime.now(UTC) - timedelta(days=200))
    before = calls.get(published["id"], conn)
    scoring.resolve_call(published["id"], conn)
    after = calls.get(published["id"], conn)
    for field in chain.SEALED_FIELDS:
        assert before[field] == after[field]
    assert after["verdict"] is not None


def test_an_already_resolved_call_is_skipped_rather_than_rescored(caller):
    caller_id, _handle, conn = caller
    published = calls.publish(caller_id, VALID, conn, now=datetime.now(UTC) - timedelta(days=200))
    scoring.resolve_call(published["id"], conn)
    again = scoring.resolve_call(published["id"], conn)
    assert again["skipped"] == "already resolved"


def test_resolve_due_reports_what_it_actually_did(caller):
    """A job that produced nothing must not look like a job that produced something. This codebase
    already lost a month of claim production to exactly that."""
    caller_id, _handle, conn = caller
    empty = scoring.resolve_due(conn, limit=0)
    assert empty["nothing_due"] is True and "note" in empty

    calls.publish(caller_id, VALID, conn, now=datetime.now(UTC) - timedelta(days=200))
    out = scoring.resolve_due(conn, limit=50)
    assert out["due"] >= 1
    assert set(out) >= {"hit", "miss", "inconclusive", "unscoreable", "resolved", "due"}


# ================================================================== the sample gate

def test_a_thin_record_shows_counts_and_refuses_a_percentage(caller):
    caller_id, _handle, conn = caller
    calls.publish(caller_id, VALID, conn)
    summary = record.summary(caller_id, conn)
    assert summary["gated"] is True
    assert summary["hit_rate"] is None
    assert summary["hit_rate_ci"] is None
    assert summary["expectancy"] is None
    assert summary["z_vs_coinflip"] is None
    assert summary["counts"]["open"] + summary["counts"]["unscoreable"] == 1
    assert summary["gate_reason"]


def test_the_gate_hides_a_rate_and_nothing_else(caller):
    """A gated caller still shows every count and every call. The gate withholds one derived
    number, it is not a place to put an inconvenient record."""
    caller_id, _handle, conn = caller
    calls.publish(caller_id, VALID, conn)
    summary = record.summary(caller_id, conn)
    assert sum(summary["counts"].values()) == 1
    assert len(calls.listing(caller_id, conn)) == 1


def test_the_sample_gate_is_25():
    assert record.SAMPLE_GATE == 25


def test_a_gated_caller_is_never_ranked(caller):
    caller_id, handle, conn = caller
    calls.publish(caller_id, VALID, conn)
    mine = next(e for e in record.board(conn) if e["handle"] == handle)
    assert mine["rank"] is None
    assert mine["summary"]["gated"] is True


# ================================================================== verification

def test_verification_issues_a_code_and_never_fetches_the_url(caller):
    caller_id, _handle, conn = caller
    started = verification.start(caller_id, "meta_tag", conn)
    assert started["code"].startswith("receipts-verify-")
    assert started["code"] in started["instructions"]

    confirmed = verification.confirm(caller_id, "https://example.com/proof", conn)
    assert confirmed["status"] == "pending"
    assert record.caller(_handle, conn)["verified_at"] is None      # not verified until reviewed


def test_a_non_https_evidence_url_is_refused(caller):
    caller_id, _handle, conn = caller
    verification.start(caller_id, "public_post", conn)
    assert "error" in verification.confirm(caller_id, "http://example.com/proof", conn)


def test_approval_stamps_the_method_and_the_evidence(caller):
    caller_id, handle, conn = caller
    started = verification.start(caller_id, "public_post", conn)
    verification.confirm(caller_id, "https://example.com/post", conn)
    verification.review(started["id"], approve=True, conn=conn)

    row = record.caller(handle, conn)
    assert row["verified_at"] is not None
    assert row["verification_method"] == "public_post"
    assert row["verification_evidence_url"] == "https://example.com/post"


def test_rejecting_a_verification_touches_no_call(caller):
    caller_id, handle, conn = caller
    calls.publish(caller_id, VALID, conn)
    started = verification.start(caller_id, "public_post", conn)
    verification.confirm(caller_id, "https://example.com/post", conn)
    verification.review(started["id"], approve=False, conn=conn)

    assert record.caller(handle, conn)["verified_at"] is None
    assert len(calls.listing(caller_id, conn)) == 1


def test_wallet_signature_is_not_offered(caller):
    """Declared in the CHECK constraint so the column never needs altering, and deliberately not
    implemented. It must not appear as a choice."""
    assert "wallet_signature" not in verification.METHODS
    caller_id, _handle, conn = caller
    assert "error" in verification.start(caller_id, "wallet_signature", conn)


# ================================================================== the measurement is sealed too
#
# Migration 034 sealed the commitment and refused to change a verdict, and said nothing about the
# nine columns the verdict is COMPUTED from. /code-review found it: `UPDATE calls SET excess_return
# = 0.42 WHERE verdict = 'miss'` succeeded, every hash still verified because none of those are
# sealed fields, and the published expectancy, the interval and every proof panel had moved. 035
# closes it, and these are the tests that keep it closed.

def _resolve_in_place(conn, call_id, **cols):
    sets = ", ".join(f"{k} = %s" for k in cols)
    with conn.cursor() as cur:
        cur.execute(f"UPDATE calls SET verdict='miss', verdict_note='n', resolved_at=now(), {sets} "  # noqa: S608
                    f"WHERE id = %s", (*cols.values(), call_id))
    conn.commit()


@pytest.mark.parametrize("column, value", [
    ("excess_return", 0.42),
    ("entry_price", 1.0),
    ("exit_price", 999.0),
    ("benchmark_entry", 1.0),
    ("benchmark_exit", 999.0),
    ("subject_return", 0.9),
    ("benchmark_return", -0.9),
    ("entry_session", "2020-01-02"),
    ("exit_session", "2020-02-02"),
    ("verdict_note", "a kinder explanation"),
])
def test_no_figure_a_resolved_call_was_scored_on_can_be_rewritten(caller, column, value):
    """The arithmetic, not only the word. A record page argues "check the numbers yourself", so a
    number that can be edited afterwards is worse than no number."""
    caller_id, _handle, conn = caller
    published = calls.publish(caller_id, VALID, conn)
    _resolve_in_place(conn, published["id"], excess_return=-0.05, entry_price=10, exit_price=9)

    with pytest.raises(psycopg.errors.RaiseException) as exc:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE calls SET {column} = %s WHERE id = %s",   # noqa: S608 — literal
                        (value, published["id"]))
    conn.rollback()
    assert "immutable" in str(exc.value)


def test_the_frozen_context_is_actually_frozen(caller):
    """034 described context_snapshot as frozen three lines above the trigger and did not seal it.
    Reconstructing it afterwards would always flatter whoever reconstructed it."""
    caller_id, _handle, conn = caller
    published = calls.publish(caller_id, VALID, conn)
    with pytest.raises(psycopg.errors.RaiseException) as exc:
        with conn.cursor() as cur:
            cur.execute("UPDATE calls SET context_snapshot = %s WHERE id = %s",
                        ('{"n_live": 999}', published["id"]))
    conn.rollback()
    assert "sealed columns" in str(exc.value)


def test_a_verdict_cannot_be_written_without_its_resolved_at(caller):
    """`resolved_at` is the switch the seal above turns on, so a verdict written without one would
    walk straight past it."""
    caller_id, _handle, conn = caller
    published = calls.publish(caller_id, VALID, conn)
    with pytest.raises(psycopg.errors.RaiseException) as exc:
        with conn.cursor() as cur:
            cur.execute("UPDATE calls SET verdict = 'hit' WHERE id = %s", (published["id"],))
    conn.rollback()
    assert "resolved_at" in str(exc.value)


def test_an_unresolved_call_can_still_be_scored(caller):
    """The boundary has to be in the right place. Sealing everything at insert would mean nothing
    could ever be scored, which is a different way of having no record."""
    caller_id, _handle, conn = caller
    published = calls.publish(caller_id, VALID, conn)
    _resolve_in_place(conn, published["id"], excess_return=-0.05)
    row = calls.get(published["id"], conn)
    assert row["verdict"] == "miss" and row["excess_return"] == pytest.approx(-0.05)


def test_a_user_can_hold_only_one_caller(caller):
    """`claim_handle` guards with a SELECT and then inserts. Two concurrent posts both passed the
    guard and inserted under different handles, so UNIQUE (handle) did not catch it, and the user
    ended up with two records that `_caller_for_user` returned interchangeably."""
    caller_id, _handle, conn = caller
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM users LIMIT 1")
        row = cur.fetchone()
    if not row:
        pytest.skip("no users in this database")
    user_id = row[0]
    with conn.cursor() as cur:
        cur.execute("UPDATE callers SET user_id = %s WHERE id = %s", (user_id, caller_id))
    conn.commit()
    try:
        with pytest.raises(psycopg.errors.UniqueViolation):
            with conn.cursor() as cur:
                cur.execute("""INSERT INTO callers (user_id, handle, display_name,
                                                    jurisdiction_attested)
                               VALUES (%s, %s, 'Second', true)""",
                            (user_id, f"second-{secrets.token_hex(4)}"))
        conn.rollback()
    finally:
        with conn.cursor() as cur:
            cur.execute("UPDATE callers SET user_id = NULL WHERE id = %s", (caller_id,))
        conn.commit()


# ================================================================== a missing exit price stays open

def test_a_symbol_whose_feed_is_behind_is_never_sealed_unscoreable(caller, monkeypatch):
    """The most dangerous mistake available in this module, and one an earlier version of it made.

    A symbol lagging the benchmark is the ROUTINE state of this price table: the free tier paces at
    roughly 45 symbols an hour, so a backlog of several hundred takes most of a day and SPY is
    fetched first on purpose. Reading that as "the symbol's feed is dead" would stamp a permanent,
    uncorrectable verdict on ordinary calls an hour before their prices arrived.
    """
    caller_id, _handle, conn = caller
    published_at = datetime.now(UTC) - timedelta(days=200)
    published = calls.publish(caller_id, VALID, conn, now=published_at)

    # A symbol series that stops AFTER entry but BEFORE the horizon closes, against a full
    # benchmark. That is exactly the shape a lagging feed has at the moment the scorer looks: an
    # entry price exists, an exit price does not yet, and the benchmark has both.
    real = scoring._series
    spy = real(conn, "SPY")
    stops = published_at.date() + timedelta(days=10)          # entry + 1, horizon is 30
    cut = [d for d in spy.days if d <= stops]
    short = Series(cut, {d: spy.close[d] for d in cut})
    assert cut and cut[-1] > published_at.date(), "the fixture must still supply an entry price"
    monkeypatch.setattr(scoring, "_series",
                        lambda c, sym: short if sym == VALID["symbol"] else real(c, sym))

    out = scoring.resolve_call(published["id"], conn)
    assert out.get("status") == "open", out
    assert calls.get(published["id"], conn)["verdict"] is None


# ================================================================== THE BENCHMARK-GAP DEFECTS
#
# Part A's proof run published twelve genuinely-due calls and hand-verified every figure. Eleven
# were exactly right. The twelfth finding was worse than a wrong number: ONE MISSING SPY SESSION
# permanently sealed `unscoreable` on a healthy, liquid symbol, with a note that named the wrong
# ticker and stated something the database contradicted. Backfilling the SPY row did not help --
# the trigger refused to correct it, which is the product working as designed on a verdict that
# should never have been written.
#
# The rule these tests pin: A CALL IS SEALED `unscoreable` IF AND ONLY IF WE HOLD NO PRICE SERIES
# FOR ITS SYMBOL. Every other gap -- the subject's feed behind, the subject's series ended, any
# gap at all in the benchmark -- leaves the call OPEN with a stored reason, and is retried. An open
# call is visible, honest and correctable. A wrong verdict is none of those, permanently.

def _weekdays(start: date, n: int) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


SESSIONS = _weekdays(date(2026, 1, 5), 160)          # 2026-01-05 .. mid-August, weekdays only
PUBLISHED = datetime(2026, 2, 2, 14, 30, tzinfo=UTC)  # long past every horizon by test time
ENTRY = date(2026, 2, 3)                              # first session strictly after publication
EXIT = date(2026, 3, 5)                               # first session on/after ENTRY + 30 days


def _step(first: float, last: float, switch: date = EXIT, days=None) -> Series:
    return Series.from_rows([(d, last if d >= switch else first) for d in (days or SESSIONS)])


def _without(series: Series, *drop: date) -> Series:
    return Series.from_rows([(d, c) for d, c in series.close.items() if d not in drop])


def _benchmark_just_past_horizon() -> list[date]:
    """Sessions up to the first one after the horizon closes: a benchmark that is fully current."""
    return [d for d in SESSIONS if d <= EXIT]


def _subject_two_days_behind() -> list[date]:
    """Sessions stopping two short of the horizon -- close enough to the benchmark's last close to
    read as a feed catching up rather than as a series that has ended."""
    return [d for d in SESSIONS if d < EXIT][:-1]


def _inject(monkeypatch, **series):
    """Point the scorer's price loader at series we control.

    `prices_eod` holds 2.2M real rows and is shared with every other plane of this product, so the
    benchmark-gap cases are built by substituting the loader rather than by writing synthetic
    prices into it. The call itself is real: published through `calls.publish`, sealed into the
    real chain, resolved by the real scorer.
    """
    monkeypatch.setattr(scoring, "_series",
                        lambda _conn, symbol: series.get(symbol, Series([], {})))


def _due(caller_id, conn, symbol=None):
    return calls.publish(caller_id, {**VALID, "horizon_days": 30,
                                     **({"symbol": symbol} if symbol else {})},
                         conn, now=PUBLISHED)


# ------------------------------------------------------------------ case 1: the entry session

def test_a_benchmark_missing_the_entry_session_leaves_the_call_open(caller, monkeypatch):
    """DEFECT 1's regression test, and the most important one in this file.

    Before the fix this sealed `unscoreable` with "our price feed for ABT ends before this call was
    published" -- while ABT's series ran six months past it.
    """
    caller_id, _handle, conn = caller
    published = _due(caller_id, conn)
    _inject(monkeypatch, ABT=_step(100.0, 130.0), SPY=_without(_step(200.0, 220.0), ENTRY))

    out = scoring.resolve_call(published["id"], conn)
    row = calls.get(published["id"], conn)

    assert out["status"] == "open", "a benchmark gap must never seal a verdict"
    assert row["verdict"] is None
    assert row["resolved_at"] is None
    assert row["open_reason_code"] == "waiting_for_benchmark"
    # The note may NAME the subject — it does, to exonerate it — but it must not BLAME it, which
    # is exactly what the sealed note used to do: "our price feed for ABT ends before this call
    # was published", while ABT's series ran six months past it.
    assert "SPY" in row["open_reason"]
    assert "not a problem with ABT" in row["open_reason"]
    assert "our side" in row["open_reason"]
    assert "feed for ABT ends" not in row["open_reason"]


def test_the_same_call_scores_correctly_once_the_benchmark_row_arrives(caller, monkeypatch):
    """The other half of DEFECT 1: staying open has to be RECOVERABLE, or it is just a slower way
    of losing the call."""
    caller_id, _handle, conn = caller
    published = _due(caller_id, conn)

    _inject(monkeypatch, ABT=_step(100.0, 130.0), SPY=_without(_step(200.0, 220.0), ENTRY))
    assert scoring.resolve_call(published["id"], conn)["status"] == "open"

    _inject(monkeypatch, ABT=_step(100.0, 130.0), SPY=_step(200.0, 220.0))   # the row arrives
    out = scoring.resolve_call(published["id"], conn)
    row = calls.get(published["id"], conn)

    assert out["verdict"] == "hit"
    assert row["entry_session"] == ENTRY.isoformat()
    assert row["exit_session"] == EXIT.isoformat()
    assert row["excess_return"] == pytest.approx(0.20, abs=1e-6)   # +30% subject, +10% benchmark
    assert row["open_reason_code"] is None, "a resolved call has no open reason"


# ------------------------------------------------------------------ case 2: the exit session

def test_a_benchmark_hole_at_the_exit_session_is_absorbed_not_failed(caller, monkeypatch):
    """Measured, and it corrects the expectation I started with. A hole AT the exit session is not
    a failure: `exit_day_for` takes the first session on or AFTER the target, so the benchmark
    simply exits on its next session while the subject exits on its own. That is deliberate --
    the benchmark gets its own `exit_day_for` precisely so a symbol that does not trade on the
    exact day cannot silently borrow SPY's date.

    The cost is a benchmark window one session longer than the subject's, which is why a holed
    benchmark is refused at BATCH level by `benchmark_health` rather than absorbed quietly. Both
    behaviours are correct and they are not in tension: per call the arithmetic still resolves,
    per batch we decline to use a series we know has gaps.
    """
    caller_id, _handle, conn = caller
    published = _due(caller_id, conn)
    _inject(monkeypatch, ABT=_step(100.0, 130.0), SPY=_without(_step(200.0, 220.0), EXIT))

    out = scoring.resolve_call(published["id"], conn)
    assert out["verdict"] == "hit"
    assert calls.get(published["id"], conn)["exit_session"] == EXIT.isoformat()


def test_a_benchmark_that_stops_before_the_horizon_leaves_the_call_open(caller, monkeypatch):
    """The exit-side half of DEFECT 1: the benchmark has an entry price but never reaches the
    horizon. Before the fix this was indistinguishable from the subject's own horizon being open."""
    caller_id, _handle, conn = caller
    published = _due(caller_id, conn)
    short_spy = [d for d in SESSIONS if d < EXIT]
    _inject(monkeypatch, ABT=_step(100.0, 130.0), SPY=_step(200.0, 220.0, days=short_spy))

    out = scoring.resolve_call(published["id"], conn)
    row = calls.get(published["id"], conn)

    assert out["status"] == "open"
    assert row["verdict"] is None
    assert row["open_reason_code"] == "waiting_for_benchmark"


def test_a_benchmark_with_no_rows_at_all_leaves_the_call_open(caller, monkeypatch):
    """Part A proved `resolve_call` sealed this when called directly -- `resolve_due`'s guard was
    the only thing standing in front of it, and a guard one layer up is not the same as a rule."""
    caller_id, _handle, conn = caller
    published = _due(caller_id, conn)
    _inject(monkeypatch, ABT=_step(100.0, 130.0))          # SPY resolves to an empty series

    assert scoring.resolve_call(published["id"], conn)["status"] == "open"
    assert calls.get(published["id"], conn)["verdict"] is None


# ------------------------------------------------------------------ case 3: refuse the batch

def test_a_holed_benchmark_refuses_the_whole_batch_and_names_the_dates(caller, monkeypatch):
    """Refusing to score is always recoverable. Sealing wrongly is not, so the batch stops."""
    caller_id, _handle, conn = caller
    published = [_due(caller_id, conn) for _ in range(3)]
    spy = _without(_step(200.0, 220.0), ENTRY, EXIT)
    _inject(monkeypatch, ABT=_step(100.0, 130.0), SPY=spy)
    monkeypatch.setattr(scoring, "market_sessions", lambda _conn, _since: SESSIONS)

    out = scoring.resolve_due(conn)

    assert out["resolved"] == 0
    assert out["refused"] is True
    assert out["warning"], "a refused batch must reach job_runs as a warning"
    assert ENTRY.isoformat() in out["missing_benchmark_sessions"]
    assert EXIT.isoformat() in out["missing_benchmark_sessions"]
    for p in published:
        assert calls.get(p["id"], conn)["verdict"] is None


def test_a_lagging_benchmark_refuses_the_whole_batch(caller, monkeypatch):
    """SPY trades every session the market is open, so a short tail is always our ingestion rather
    than a market fact. CLAUDE.md 0h: SPY is fetched first precisely because of this."""
    caller_id, _handle, conn = caller
    published = _due(caller_id, conn)
    _inject(monkeypatch, ABT=_step(100.0, 130.0),
            SPY=_step(200.0, 220.0, days=SESSIONS[:40]))
    monkeypatch.setattr(scoring, "market_sessions", lambda _conn, _since: SESSIONS)

    out = scoring.resolve_due(conn)
    assert out["refused"] is True and out["resolved"] == 0
    assert calls.get(published["id"], conn)["verdict"] is None


def test_a_healthy_benchmark_does_not_refuse(caller, monkeypatch):
    """The guard has to be quiet in normal operation or it will be switched off."""
    caller_id, _handle, conn = caller
    published = _due(caller_id, conn)
    _inject(monkeypatch, ABT=_step(100.0, 130.0), SPY=_step(200.0, 220.0))
    monkeypatch.setattr(scoring, "market_sessions", lambda _conn, _since: SESSIONS)

    out = scoring.resolve_due(conn)
    assert out.get("refused") is not True
    assert calls.get(published["id"], conn)["verdict"] == "hit"


def test_the_live_benchmark_is_healthy_right_now():
    """Measured, not assumed: the guard above would block every run if SPY were holed today."""
    with db.connect() as conn:
        health = scoring.benchmark_health(conn)
    assert health["ok"] is True, f"SPY is not healthy: {health}"


# ------------------------------------------------------------------ case 4: the no-op write

def test_writing_a_verdict_onto_a_resolved_call_reports_a_no_op(caller, monkeypatch):
    """`_write`'s UPDATE carries `AND verdict IS NULL` and used to ignore rowcount, so it returned
    a fabricated verdict the row never received -- and `resolve_due` counted that into
    `job_runs.detail`. A run that wrote nothing could report hits."""
    caller_id, _handle, conn = caller
    published = _due(caller_id, conn)
    _inject(monkeypatch, ABT=_step(100.0, 130.0), SPY=_step(200.0, 220.0))
    assert scoring.resolve_call(published["id"], conn)["verdict"] == "hit"

    out = scoring._write(conn, published["id"], "miss", "a verdict this call never received",
                         {"excess_return": -0.99})

    assert out["no_op"] is True
    assert out.get("verdict") != "miss"
    row = calls.get(published["id"], conn)
    assert row["verdict"] == "hit"
    assert row["excess_return"] == pytest.approx(0.20, abs=1e-6)


def test_resolve_due_counts_no_ops_separately(caller, monkeypatch):
    """SCOPED TO THE SCRATCH CALLER, and that is not tidiness.

    This used to call `resolve_due(conn)` unscoped, against the live database, with `_series`
    monkeypatched to a fixture. It therefore picked up every OTHER open call that had reached its
    horizon — including a real stranger's public ABT call — and rewrote that call's public "why is
    this still open" sentence from prices that do not exist. Under a fixture series that happened
    to span the horizon it would have sealed a permanent verdict on it instead.
    """
    caller_id, _handle, conn = caller
    _due(caller_id, conn)
    _inject(monkeypatch, ABT=_step(100.0, 130.0), SPY=_step(200.0, 220.0))
    monkeypatch.setattr(scoring, "market_sessions", lambda _conn, _since: SESSIONS)
    assert scoring.resolve_due(conn, caller_id=caller_id)["resolved"] == 1
    assert "no_ops" in scoring.resolve_due(conn, caller_id=caller_id)


def test_resolve_due_scoped_to_one_caller_touches_no_other_row(caller, monkeypatch):
    """The guard on the accident above, so it cannot come back by someone dropping the argument."""
    caller_id, _handle, conn = caller
    _due(caller_id, conn)
    _inject(monkeypatch, ABT=_step(100.0, 130.0), SPY=_step(200.0, 220.0))
    monkeypatch.setattr(scoring, "market_sessions", lambda _conn, _since: SESSIONS)

    with conn.cursor() as cur:
        cur.execute("SELECT id, open_checked_at FROM calls "
                    "WHERE verdict IS NULL AND caller_id <> %s", (caller_id,))
        before = dict(cur.fetchall())

    scoring.resolve_due(conn, caller_id=caller_id)

    with conn.cursor() as cur:
        cur.execute("SELECT id, open_checked_at, verdict FROM calls "
                    "WHERE id = ANY(%s)", (list(before) or [-1],))
        for cid, checked, verdict in cur.fetchall():
            assert verdict is None, f"call {cid} was sealed by a scoped batch"
            assert checked == before[cid], f"call {cid} had its disclosure rewritten"


# ------------------------------------------------------------------ case 5: the open reason

def test_a_subject_whose_feed_is_merely_behind_says_so(caller, monkeypatch):
    caller_id, _handle, conn = caller
    published = _due(caller_id, conn)
    # The benchmark has reached the horizon; the subject is two sessions short of it. Both series
    # end in the same week, which is what "the feed is catching up" actually looks like.
    _inject(monkeypatch, ABT=_step(100.0, 130.0, days=_subject_two_days_behind()),
            SPY=_step(200.0, 220.0, days=_benchmark_just_past_horizon()))

    assert scoring.resolve_call(published["id"], conn)["status"] == "open"
    row = calls.get(published["id"], conn)
    assert row["open_reason_code"] == "waiting_for_subject_price"
    assert row["open_checked_at"] is not None


def test_a_subject_whose_series_ended_long_ago_is_named_as_such(caller, monkeypatch):
    """Delisted and merely-behind cannot be told apart with certainty, and this is a DISCLOSURE on
    an editable column rather than a verdict -- which is the only place a heuristic belongs here.
    CLAUDE.md 0z forbids letting the benchmark settle a VERDICT; it does not forbid saying what the
    data looks like."""
    caller_id, _handle, conn = caller
    published = _due(caller_id, conn)
    dead = [d for d in SESSIONS if d <= date(2026, 1, 20)]
    _inject(monkeypatch, ABT=_step(100.0, 130.0, days=dead), SPY=_step(200.0, 220.0))

    assert scoring.resolve_call(published["id"], conn)["status"] == "open"
    row = calls.get(published["id"], conn)
    assert row["open_reason_code"] == "subject_series_ended"
    assert "2026-01-20" in row["open_reason"]


def test_the_open_reason_is_replaced_as_the_reason_changes(caller, monkeypatch):
    """A non-sealed column on purpose: the reason a call is open is a live fact, not a commitment."""
    caller_id, _handle, conn = caller
    published = _due(caller_id, conn)

    _inject(monkeypatch, ABT=_step(100.0, 130.0), SPY=_without(_step(200.0, 220.0), ENTRY))
    scoring.resolve_call(published["id"], conn)
    assert calls.get(published["id"], conn)["open_reason_code"] == "waiting_for_benchmark"

    _inject(monkeypatch, ABT=_step(100.0, 130.0, days=_subject_two_days_behind()),
            SPY=_step(200.0, 220.0, days=_benchmark_just_past_horizon()))
    scoring.resolve_call(published["id"], conn)
    assert calls.get(published["id"], conn)["open_reason_code"] == "waiting_for_subject_price"


def test_no_price_series_at_all_is_still_the_one_thing_that_seals(caller, monkeypatch):
    """The rule has to have teeth on both sides: an unpriceable symbol is a real, permanent fact
    about the call and must still be sealed, or the record fills up with rows that never resolve."""
    caller_id, _handle, conn = caller
    published = _due(caller_id, conn)
    _inject(monkeypatch, SPY=_step(200.0, 220.0))          # ABT resolves to an empty series

    out = scoring.resolve_call(published["id"], conn)
    row = calls.get(published["id"], conn)
    assert out["verdict"] == "unscoreable"
    assert row["verdict"] == "unscoreable" and row["resolved_at"] is not None
    assert "ABT" in row["verdict_note"]


# ------------------------------------------------------------------ case 6: the strict floor

def test_the_noise_floor_is_strict_so_exactly_two_percent_is_a_hit():
    """`docs/receipts_gap_analysis.md` stated this as |excess| <= 2%. The code is `<`, measured.
    The document was corrected rather than the code: a move that reaches the floor has cleared it."""
    assert scoring.NOISE_FLOOR == 0.02
    assert scoring.verdict_for("up", 0.02)[0] == "hit"
    assert scoring.verdict_for("up", -0.02)[0] == "miss"
    assert scoring.verdict_for("down", -0.02)[0] == "hit"
    assert scoring.verdict_for("up", 0.019999)[0] == "inconclusive"


def test_a_call_landing_exactly_on_the_floor_resolves_hit(caller, monkeypatch):
    caller_id, _handle, conn = caller
    published = _due(caller_id, conn)
    # +12% subject against +10% benchmark = exactly +2.000000% excess
    _inject(monkeypatch, ABT=_step(100.0, 112.0), SPY=_step(200.0, 220.0))

    out = scoring.resolve_call(published["id"], conn)
    row = calls.get(published["id"], conn)
    assert row["excess_return"] == pytest.approx(0.02, abs=1e-9)
    assert out["verdict"] == "hit"
    assert "noise floor" not in (row["verdict_note"] or "")


def test_a_note_never_contradicts_itself_at_the_floor(caller):
    """The note printed "moved +2.00% vs SPY, inside the 2% noise floor" for 0.019959, because
    {:+.2%} rounds up. On a product whose pitch is that its numbers mean exactly what they say, a
    self-contradicting sentence is a real defect."""
    for excess in (0.019959, -0.019992, 0.0199999):
        verdict, note = scoring.verdict_for("up", excess)
        assert verdict == "inconclusive"
        assert "2.00%" not in note, f"{excess} rendered as 2.00% beside a 2% floor: {note}"
        assert "noise floor" in note


def test_a_thin_name_with_no_trade_on_the_entry_session_rolls_forward_and_scores(caller, monkeypatch):
    """The free Alpaca tier serves the IEX feed, and IEX does not print every symbol every day.

    So a thinly traded name has HOLES in its series — days the market was open and this symbol
    simply did not trade there. That is not the same shape as a feed that has stopped, and it must
    not be treated like one: the series continues past the horizon, so an honest verdict exists.

    `entry_day_after` and `exit_day_for` read the SYMBOL'S OWN sessions (`_first_gt` / `_first_ge`),
    not the market calendar, so a hole rolls forward to the next session the symbol actually has.
    This pins that, because the obvious alternative implementation — index into the benchmark's
    calendar and look the symbol up — would return no price on exactly these names and seal or
    hang every one of them.
    """
    caller_id, _handle, conn = caller
    published_at = datetime.now(UTC) - timedelta(days=200)
    published = calls.publish(caller_id, VALID, conn, now=published_at)

    real = scoring._series
    spy = real(conn, "SPY")
    as_of = published_at.date()
    after = [d for d in spy.days if d > as_of]
    assert len(after) > 40, "the benchmark fixture must span the horizon"

    # Punch out the first session after publication AND the session the 30-day horizon lands on,
    # which are the two days the arithmetic reaches for by name.
    horizon_day = as_of + timedelta(days=VALID["horizon_days"])
    holes = {after[0], next(d for d in spy.days if d >= horizon_day)}
    kept = [d for d in spy.days if d not in holes]
    thin = Series(kept, {d: spy.close[d] for d in kept})
    monkeypatch.setattr(scoring, "_series",
                        lambda c, sym: thin if sym == VALID["symbol"] else real(c, sym))

    out = scoring.resolve_call(published["id"], conn)
    assert out.get("status") != "open", f"a name with holes must still resolve: {out}"
    assert out["verdict"] in ("hit", "miss", "inconclusive"), out
    assert out["verdict"] != "unscoreable", "a hole is not an absent series"
    # And it entered on a day the symbol actually traded, not on the hole.
    assert date.fromisoformat(str(out["entry_session"])) not in holes


def test_a_thin_name_whose_series_ends_before_the_horizon_waits_and_never_seals(caller, monkeypatch):
    """The other half of the same feed reality, asserted separately so a failure names which one.

    A hole rolls forward; an END has nothing to roll to. That case must stay OPEN forever rather
    than seal, because we cannot tell a delisting from a feed that has given up, and a sealed
    verdict can never be corrected.
    """
    caller_id, _handle, conn = caller
    published_at = datetime.now(UTC) - timedelta(days=200)
    published = calls.publish(caller_id, VALID, conn, now=published_at)

    real = scoring._series
    spy = real(conn, "SPY")
    as_of = published_at.date()
    stops = as_of + timedelta(days=5)              # after entry, well before the 30-day horizon
    kept = [d for d in spy.days if d <= stops]
    assert kept and kept[-1] > as_of
    ends = Series(kept, {d: spy.close[d] for d in kept})
    monkeypatch.setattr(scoring, "_series",
                        lambda c, sym: ends if sym == VALID["symbol"] else real(c, sym))

    out = scoring.resolve_call(published["id"], conn)
    assert out.get("status") == "open", out
    assert out.get("open_reason_code") in (
        "waiting_for_subject_price", "subject_series_ended"), out
