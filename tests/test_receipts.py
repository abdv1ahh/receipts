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

import secrets
from datetime import UTC, datetime, timedelta

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


def test_the_proof_panel_arithmetic_reconciles(caller):
    """An investor should be able to check this with a calculator, so the stored components have to
    actually produce the stored excess return."""
    caller_id, _handle, conn = caller
    published = calls.publish(caller_id, VALID, conn, now=datetime.now(UTC) - timedelta(days=200))
    scoring.resolve_call(published["id"], conn)
    r = calls.get(published["id"], conn)

    assert r["verdict"] in ("hit", "miss", "inconclusive")
    assert r["subject_return"] == pytest.approx(r["exit_price"] / r["entry_price"] - 1, abs=1e-6)
    assert r["benchmark_return"] == pytest.approx(
        r["benchmark_exit"] / r["benchmark_entry"] - 1, abs=1e-6)
    assert r["excess_return"] == pytest.approx(r["subject_return"] - r["benchmark_return"], abs=1e-5)


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
