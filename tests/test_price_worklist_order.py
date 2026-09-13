"""The price work list must be ordered by STALENESS, never by symbol.

This is a correctness test, not a performance one, and it exists because the alphabetical version
shipped and did measurable damage. Every selector in `backtest/run.py` used to end in
`ORDER BY symbol` or `sorted(...)`. A free-tier pass cannot finish the list, so every run walked
A->Z and died in the same place: measured 2026-09-09, 0 of 500 symbols had a bar at the latest NYSE
session, the 39 that reached the newest day were one contiguous alphabetical block ending at
`PEB-PH`, and the 79 stalest were the tail from `PFX` to `YEXT`.

Two properties are asserted, and the second is the one that would rot quietly:

  1. the oldest data comes first, so a run that is cut short leaves the table EVENLY stale
  2. symbols of EQUAL staleness are not returned alphabetically — otherwise the bias simply moves
     inside each staleness tier and the first assertion still passes
"""
from __future__ import annotations

import secrets
from datetime import date, timedelta

import pytest

try:
    from tradeos import db
    from tradeos.backtest import run as btrun
    _IMPORTS_OK = True
except Exception:                                                   # pragma: no cover
    _IMPORTS_OK = False


def _db_reachable() -> bool:
    if not _IMPORTS_OK:
        return False
    try:
        with db.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT to_regclass('prices_eod')")
            return cur.fetchone()[0] is not None
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _db_reachable(),
                                reason="no database reachable; the work-list order test needs one")


@pytest.fixture
def staggered_symbols():
    """Scratch symbols whose staleness runs OPPOSITE to their alphabetical order.

    `ZZTEST-A` is the freshest and `ZZTEST-E` the stalest, so an alphabetical selector returns
    A,B,C,D,E and a staleness-ordered one returns E,D,C,B,A. The two orderings are exact reverses,
    which makes the assertion unambiguous rather than merely "not equal".
    """
    tag = secrets.token_hex(3).upper()
    names = [f"ZZ{tag}{c}" for c in "ABCDE"]
    today = date.today()
    with db.connect() as conn:
        with conn.cursor() as cur:
            for i, sym in enumerate(names):
                # A is 10 days old, E is 50 — freshest first alphabetically.
                last = today - timedelta(days=10 * (i + 1))
                cur.execute(
                    """INSERT INTO prices_eod (symbol, day, close, source)
                       VALUES (%s,%s,%s,'test') ON CONFLICT (symbol, day) DO NOTHING""",
                    (sym, last, 100.0 + i),
                )
        conn.commit()
        yield names, conn
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute("DELETE FROM prices_eod WHERE symbol = ANY(%s)", (names,))
        conn.commit()


def test_stale_worklist_is_ordered_by_staleness_not_alphabetically(staggered_symbols):
    names, conn = staggered_symbols
    got = [s for s in btrun.symbols_stale(conn, date.today()) if s in names]

    assert got == sorted(names, reverse=True) or got == list(reversed(names)), (
        f"expected oldest-data-first {list(reversed(names))}, got {got}"
    )
    # The explicit statement of the bug: the result must NOT be the alphabetical order.
    assert got != sorted(names), "work list came back alphabetically — the A->Z bias is back"
    # And the property that actually matters, stated directly rather than via the ordering above.
    assert got[0] == names[-1], "the stalest symbol must be fetched first"


def test_equal_staleness_does_not_fall_back_to_alphabetical(staggered_symbols):
    """Symbols with IDENTICAL staleness must not come back A->Z.

    Without a non-alphabetical tie-break the bias moves inside each staleness tier: every symbol
    with no data at all is equally stale, so a truncated pass over that tier would still take an
    alphabetically biased sample. `md5(symbol)` is the tie-break; this asserts it is doing
    something.
    """
    names, conn = staggered_symbols
    same_day = date.today() - timedelta(days=90)
    with conn.cursor() as cur:
        for sym in names:
            cur.execute(
                """INSERT INTO prices_eod (symbol, day, close, source)
                   VALUES (%s,%s,%s,'test') ON CONFLICT (symbol, day) DO NOTHING""",
                (sym, same_day, 50.0),
            )
        # Collapse them onto one staleness value by removing the staggered rows.
        cur.execute("DELETE FROM prices_eod WHERE symbol = ANY(%s) AND day <> %s", (names, same_day))
    conn.commit()

    got = [s for s in btrun.symbols_stale(conn, date.today()) if s in names]
    assert sorted(got) == sorted(names), "the tie-break must not drop or duplicate symbols"
    assert got != sorted(names), (
        "symbols of equal staleness came back alphabetically; the md5 tie-break is missing, and "
        "the A->Z bias survives inside each staleness tier"
    )


def test_spy_leads_the_worklist_even_though_it_is_not_the_stalest(staggered_symbols):
    """SPY is the one deliberate exception to staleness ordering.

    A stale benchmark makes every other symbol unscoreable however current that symbol is, so SPY
    must never sit behind 400 others in a queue a rate limit may cut short. It moves exactly one
    symbol, which is why it does not reintroduce a bias.
    """
    names, conn = staggered_symbols
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM prices_eod WHERE symbol = 'SPY'")
        if cur.fetchone()[0] == 0:
            pytest.skip("no SPY series in this database")

    # A cutoff far in the future makes every symbol stale, SPY included.
    got = btrun.symbols_stale(conn, date.today() + timedelta(days=365))
    assert got[0] == "SPY", f"SPY must lead the work list, got {got[:3]}"
    assert got.count("SPY") == 1, "SPY must appear exactly once"


def test_no_selector_sorts_by_symbol():
    """A source-level guard, because the SQL is what regresses.

    The three `symbols_for_clusters*` selectors need a populated `signal_clusters` join to test
    behaviourally, which makes them awkward to fixture. Their ordering is a one-line property of
    the SQL, so it is asserted against the source: none of them may end in `ORDER BY symbol`, and
    none may wrap its result in `sorted(...)`.
    """
    import inspect
    src = inspect.getsource(btrun)
    for fn in ("symbols_for_clusters", "symbols_for_clusters_missing",
               "symbols_for_clusters_missing_history", "symbols_stale"):
        body = src.split(f"def {fn}(")[1].split("\ndef ")[0]
        assert "ORDER BY symbol\"" not in body and "ORDER BY symbol'" not in body, \
            f"{fn} orders alphabetically"
        assert "sorted({r[0]" not in body, \
            f"{fn} wraps its result in sorted(), which is the alphabetical bias by another name"
