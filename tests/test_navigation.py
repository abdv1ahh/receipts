"""Navigation invariants, asserted against the front end's own source.

There is no JavaScript test runner in this repo and adding one is not this change's job, so these
read App.jsx the way `test_sources.py` reads a Python module. The failure mode being guarded is a
specific one that already happened here: `portfolios.jsx` was imported and rendered but absent from
ROUTES, so an entire paid feature was unreachable while the pricing page advertised it. A test that
asserts the shape of the code is the right instrument for a bug that IS the shape of the code.

THE RAIL IS NOW FOUR ITEMS, and the tables it used to have to agree with are gone. NAV_LABELS,
SIDEBAR, MORE and CMD_ITEMS existed because there were twenty-one surfaces in three groups with a
hidden tier below them; four destinations need one table. What survives from the old file is the
invariant, not the machinery: everything importable is reachable, and everything reachable leads
somewhere real.

Skips where the front end source is not present, which is how the production image is built: only
`tradeos/` and `tests/` are copied in, so a checkout is what these need and a container is not.
"""
from __future__ import annotations

import pathlib
import re

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "frontend" / "src"
APP_JSX = SRC / "App.jsx"

pytestmark = pytest.mark.skipif(
    not APP_JSX.exists(),
    reason="frontend source is not mounted here; these read App.jsx from a checkout")


def _app_source() -> str:
    return APP_JSX.read_text()


def test_every_receipts_surface_is_on_the_rail():
    src = _app_source()
    labels = src.split("const NAV_LABELS = {", 1)[1].split("};", 1)[0]
    for route in ("board", "publish", "record", "methodology"):
        assert f"{route}:" in labels, f"{route} missing from NAV_LABELS"
    # ROUTES is built from Object.keys(NAV_LABELS), so being in NAV_LABELS is what makes a surface
    # addressable. Assert that wiring rather than restating the list.
    assert "new Set([...Object.keys(NAV_LABELS)" in src


def test_the_app_lands_on_the_board():
    src = _app_source()
    assert 'ROUTES.has(route.path) ? route.path : "board"' in src
    assert 'setUser(u); setView("board")' in src


def test_the_addressable_surfaces_that_are_deliberately_off_the_rail_are_still_reachable():
    """Off the rail, not bricked up. Claiming a handle is a one-time act, so a permanent nav item
    for it is dead weight for everyone who has done it — but it is the one thing this product ever
    asks a stranger to do, so it needs a URL. `call` is reached from every row of a record, and
    `verify`/`reset` are reached from an email; without them the link falls through to the
    catch-all and lands on the Board with the token silently ignored."""
    src = _app_source()
    routes = src.split("const ROUTES = new Set(", 1)[1].split(");", 1)[0]
    for route in ("auth", "claim", "call", "verify", "reset"):
        assert f'"{route}"' in routes, f"{route} is unreachable even by URL"


def test_every_surface_the_app_renders_is_in_routes():
    """The portfolios bug, generalised. A `view === "x"` branch with no "x" in ROUTES is a screen
    that exists, is written, is imported — and cannot be reached, because an unrecognised path
    falls back to the Board before the branch is ever evaluated."""
    src = _app_source()
    routes = src.split("const ROUTES = new Set(", 1)[1].split(");", 1)[0]
    labels = src.split("const NAV_LABELS = {", 1)[1].split("};", 1)[0]
    rendered = set(re.findall(r'view === "([a-z-]+)"', src))
    for view in sorted(rendered):
        assert f'"{view}"' in routes or f"{view}:" in labels, f'"{view}" is rendered but unreachable'


def test_no_jsx_is_left_in_the_tree_that_nothing_imports():
    """The other direction, and the one this deletion could plausibly get wrong: a .jsx left
    behind, imported by nobody, rendering nothing. It costs a reader's time and reads as a live
    feature. Resolved across every file rather than App.jsx alone, because a shared module like
    `receiptsui.jsx` is legitimately imported by the surfaces and never by the router.

    `main.jsx` is exempt: it is the Vite entry point named in index.html, so nothing imports it by
    construction."""
    imported = set()
    for f in SRC.glob("*.jsx"):
        imported |= set(re.findall(r'from "\./([A-Za-z0-9_-]+)\.jsx"', f.read_text()))
    on_disk = {p.stem for p in SRC.glob("*.jsx")} - {"App", "main"}
    orphans = on_disk - imported
    assert not orphans, f"in the tree and imported by nothing: {sorted(orphans)}"


def test_there_is_no_door_to_a_surface_that_was_deleted():
    """Every research surface came off the rail before it came out of the tree. Neither the rail
    nor the router may still name one."""
    src = _app_source()
    gone = ("dashboard", "brief", "trending", "alerts", "screener", "portfolios", "radar", "globe",
            "exposure", "library", "community", "trader", "crypto", "news", "events", "journal",
            "watchlist", "assistant", "search", "integrations", "pricing", "home", "ledger",
            "asset", "profile", "notifications", "signal-methodology")
    for view in gone:
        assert f'view === "{view}"' not in src, f"{view} still has a render branch"
        assert f'"{view}"' not in src.split("const ROUTES", 1)[1].split(");", 1)[0], \
            f"{view} is still in ROUTES"
