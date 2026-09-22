"""The baseline and the 37 ordered files must produce the same database.

WHY THIS IS A TEST AND NOT A CHECKLIST ITEM. `migrations/baseline/001_baseline.sql` is what every
NEW install gets, and the 37 files in `migrations/` are what the author's database has already
applied. Two paths to one schema is a drift problem by construction: the day somebody adds
migration 38 and forgets the baseline, a fresh install and an upgraded one stop being the same
product, and nothing else in the suite would notice — every other test runs against whichever
database it is handed.

WHAT DRIFT WOULD COST, specifically. The baseline was assembled from `pg_dump -t`, which emits
CREATE TRIGGER and NOT the function the trigger calls: the raw dump of 21 tables contained three
CREATE TRIGGER statements and zero CREATE FUNCTION. Postgres accepts a trigger pointing at a
missing function at CREATE time and fails at the first UPDATE — so the failure mode this guards is
an append-only record whose append-only trigger does not exist, discovered by a caller finding they
can edit a sealed call.

Both databases are created and dropped here. Neither is the one the rest of the suite uses, and
neither is the author's.
"""
from __future__ import annotations

import os
import re
import subprocess

import pytest

try:
    import psycopg

    from tradeos import config, db
    _IMPORTS_OK = True
except Exception:                                             # pragma: no cover
    _IMPORTS_OK = False


# Every table the Receipts code touches. Written out rather than derived from the baseline file,
# so that adding a table to the baseline and forgetting it here is a visible omission rather than a
# silently widened check.
KEPT_TABLES = ("api_keys", "audit_log", "auth_tokens", "caller_verifications", "callers", "calls",
               "feature_flags", "feed_health", "ingest_rejects", "invites", "job_runs",
               "login_attempts", "oauth_identities", "oauth_states", "prices_eod",
               "schema_migrations", "sessions", "subscriptions", "users")


def _admin_url() -> str | None:
    """A connection to `postgres`, from the app's own URL, so this needs no extra configuration."""
    if not _IMPORTS_OK:
        return None
    try:
        url = config.database_url()
    except Exception:
        return None
    return re.sub(r"/[^/?]+(\?|$)", r"/postgres\1", url)


def _reachable() -> bool:
    url = _admin_url()
    if not url:
        return False
    try:
        with psycopg.connect(url, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
        return True
    except Exception:
        return False


def _have_pg_dump() -> bool:
    try:
        # S607/S603 suppressed together and for one reason: every argument this file passes to
        # pg_dump is a literal written above (KEPT_TABLES) or a URL derived from the app's own
        # DATABASE_URL. Nothing here is user input, and pinning an absolute path would break the
        # one thing that varies legitimately between a container and a developer's machine.
        subprocess.run(["pg_dump", "--version"], capture_output=True, check=True)  # noqa: S603, S607
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _reachable(), reason="needs a reachable postgres to build two scratch databases")

# Only the schema DIFF needs pg_dump. The trigger checks below need psycopg and nothing else, and
# they are the ones that must never go quiet: "the append-only trigger does not fire" is not
# allowed to be invisible for want of a command-line tool.
needs_pg_dump = pytest.mark.skipif(
    not _have_pg_dump(), reason="pg_dump is not on PATH here; the schema diff needs it")


def _scratch(name: str):
    admin = _admin_url()
    with psycopg.connect(admin, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(f'DROP DATABASE IF EXISTS "{name}"')
        cur.execute(f'CREATE DATABASE "{name}"')
    return re.sub(r"/[^/?]+(\?|$)", f"/{name}\\1", admin)


def _drop(name: str) -> None:
    with psycopg.connect(_admin_url(), autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(f'DROP DATABASE IF EXISTS "{name}"')


def _schema(url: str, tables: tuple[str, ...]) -> str:
    """`pg_dump --schema-only`, normalised so only real differences survive.

    The version banner and the \\restrict token change between runs and say nothing about the
    schema; comparing them would make this test fail for reasons nobody can act on.
    """
    args = ["pg_dump", "--schema-only", "--no-owner", "--no-privileges"]
    for t in tables:
        args += ["-t", f"public.{t}"]
    out = subprocess.run([*args, url], capture_output=True,   # noqa: S603 — see _have_pg_dump
                         text=True, check=True).stdout
    out = re.sub(r"^\\(?:un)?restrict.*$", "", out, flags=re.M)
    out = re.sub(r"^-- Dumped .*$", "", out, flags=re.M)
    return re.sub(r"\n{2,}", "\n", out).strip()


def _migrate(url: str, *, force_ordered: bool) -> None:
    """Run the real runner against `url`.

    `force_ordered` points BASELINE_DIR at a directory with no .sql in it, which is exactly the
    condition `run_migrations` already handles — so the ordered path is exercised as written rather
    than through a second code path invented for the test.
    """
    original_url = os.environ.get("DATABASE_URL")
    original_baseline = db.BASELINE_DIR
    os.environ["DATABASE_URL"] = url
    if force_ordered:
        db.BASELINE_DIR = db.MIGRATIONS_DIR / "does-not-exist"
    try:
        with psycopg.connect(url) as conn:
            db.run_migrations(conn)
    finally:
        db.BASELINE_DIR = original_baseline
        if original_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = original_url


@pytest.fixture(scope="module")
def two_databases():
    fresh, historical = "receipts_baseline_check", "receipts_ordered_check"
    try:
        _migrate(_scratch(fresh), force_ordered=False)
        _migrate(_scratch(historical), force_ordered=True)
        yield (re.sub(r"/[^/?]+(\?|$)", f"/{fresh}\\1", _admin_url()),
               re.sub(r"/[^/?]+(\?|$)", f"/{historical}\\1", _admin_url()))
    finally:
        _drop(fresh)
        _drop(historical)


def test_the_baseline_reports_every_version_it_stands_in_for(two_databases):
    """A fresh install has to be indistinguishable from a migrated one to the runner itself.
    Without the 1..37 rows, the very next `cli migrate` replays all 37 on top of this schema and
    the first one fails on a table that already exists."""
    fresh, _ = two_databases
    with psycopg.connect(fresh) as conn:
        assert db.applied_versions(conn) == set(range(1, 38))


def test_the_append_only_trigger_survives_the_baseline(two_databases):
    """THE one that matters. pg_dump's per-table mode emits CREATE TRIGGER without the function it
    calls, and Postgres accepts that until the first UPDATE — so a baseline built by piping pg_dump
    into a file ships an append-only record that is not append-only, and nothing finds out until
    somebody edits a sealed call."""
    fresh, _ = two_databases
    with psycopg.connect(fresh) as conn, conn.cursor() as cur:
        cur.execute("SELECT tgname FROM pg_trigger WHERE tgrelid = 'calls'::regclass "
                    "AND NOT tgisinternal")
        assert [r[0] for r in cur.fetchall()] == ["calls_append_only_trg"]
        cur.execute("SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
                    "WHERE n.nspname = 'public' AND p.proname = ANY(%s)",
                    (["calls_append_only", "callers_handle_immutable", "forbid_mutation"],))
        assert cur.fetchone()[0] == 3, "a trigger function is missing; the trigger is a dead letter"


def test_a_sealed_call_cannot_be_edited_on_a_baselined_database(two_databases):
    """The trigger existing is not the same as the trigger working. This publishes a row the way
    the product does and then tries to change it, which is the only check that cannot be satisfied
    by a trigger pointing at the wrong function."""
    fresh, _ = two_databases
    with psycopg.connect(fresh) as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO callers (handle, display_name, kind, jurisdiction_attested) "
                    "VALUES ('baseline-check', 'Baseline', 'human', true) RETURNING id")
        caller_id = cur.fetchone()[0]
        cur.execute("""INSERT INTO calls (caller_id, seq, symbol, direction, horizon_days,
                                          confidence, thesis, published_at, knowable_time,
                                          prev_hash, content_hash, verdict, verdict_note,
                                          resolved_at, excess_return)
                       VALUES (%s, 1, 'ABT', 'up', 7, 'low', 'a thesis', now(), now(),
                               'p', 'c', 'miss', 'n', now(), -0.05) RETURNING id""", (caller_id,))
        call_id = cur.fetchone()[0]
        conn.commit()

        for column, value in (("verdict", "hit"), ("excess_return", 0.42), ("thesis", "rewritten")):
            with pytest.raises(psycopg.errors.RaiseException):
                cur.execute(f"UPDATE calls SET {column} = %s WHERE id = %s",   # noqa: S608 — literal
                            (value, call_id))
            conn.rollback()
        with pytest.raises(psycopg.errors.RaiseException):
            cur.execute("DELETE FROM calls WHERE id = %s", (call_id,))
        conn.rollback()


@needs_pg_dump
def test_both_paths_produce_the_same_schema(two_databases):
    """The whole point. A fresh install and an upgraded one are the same product or they are not.

    SCOPED TO THE 19 KEPT TABLES, and the scope is the finding rather than a weakening. Release
    plan §C says to diff the two databases whole and expect them to be identical, and they are not
    and must not be: the baseline creates 19 tables and the 37 ordered files create 64, because 45
    of them belong to subsystems that were deleted. Comparing the whole schema would fail forever
    on exactly the difference the baseline exists to create.

    What has to be identical is every table Receipts actually touches — measured here at 739 lines
    of DDL each, byte for byte, triggers and constraints and defaults included.
    """
    fresh, historical = two_databases
    a, b = _schema(fresh, KEPT_TABLES), _schema(historical, KEPT_TABLES)
    if a != b:
        import difflib
        diff = "\n".join(list(difflib.unified_diff(
            b.splitlines(), a.splitlines(), "from the 37 ordered files", "from the baseline",
            lineterm=""))[:80])
        raise AssertionError("the baseline and the ordered migrations disagree:\n" + diff)
