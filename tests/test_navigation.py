"""Navigation and pricing invariants, asserted against the front end's own source.

There is no JavaScript test runner in this repo and adding one is not this change's job, so these
read App.jsx the way `test_sources.py` reads a Python module. The failure mode being guarded is a
specific one that already happened here: `portfolios.jsx` was imported and rendered but absent from
ROUTES, so an entire paid feature was unreachable while the pricing page advertised it. A test that
asserts the shape of the code is the right instrument for a bug that IS the shape of the code.

Skips where the front end source is not present, which is how the production image is built: only
`tradeos/` and `tests/` are copied in, so a checkout is what these need and a container is not.
"""
from __future__ import annotations

import pathlib

import pytest

APP_JSX = pathlib.Path(__file__).resolve().parents[1] / "frontend" / "src" / "App.jsx"

pytestmark = pytest.mark.skipif(
    not APP_JSX.exists(),
    reason="frontend source is not mounted here; these read App.jsx from a checkout")

#
# There is no JavaScript test runner in this repo and adding one is not this change's job, so these
# read App.jsx the way `test_sources.py` reads a module: the failure mode being guarded is a
# specific one that already happened here. `portfolios.jsx` was imported and rendered but absent
# from ROUTES, so an entire paid feature was unreachable while the pricing page advertised it.

APP_JSX = pathlib.Path(__file__).resolve().parents[1] / "frontend" / "src" / "App.jsx"


def _app_source() -> str:
    return APP_JSX.read_text()


def test_every_receipts_route_is_in_all_three_tables():
    """NAV_LABELS, ROUTES and CMD_ITEMS. A route in one and not the others is either an
    unreachable surface or a dead menu entry."""
    src = _app_source()
    labels = src.split("const NAV_LABELS = {", 1)[1].split("};", 1)[0]
    for route in ("board", "publish", "record", "methodology"):
        assert f"{route}:" in labels or f'"{route}":' in labels, f"{route} missing from NAV_LABELS"
    # ROUTES is built from Object.keys(NAV_LABELS), and CMD_ITEMS from the same, so being in
    # NAV_LABELS is what puts a route in all three. Assert that wiring rather than restating it.
    assert "new Set([...Object.keys(NAV_LABELS)" in src
    assert "Object.keys(NAV_LABELS).map((v) => ({ v, label: NAV_LABELS[v]" in src


def test_the_app_lands_on_the_board():
    src = _app_source()
    assert 'ROUTES.has(route.path) ? route.path : "board"' in src
    assert 'setUser(u); setView("board")' in src


def test_the_hidden_surfaces_are_gone_from_navigation():
    """Radar, Exposure, The World, Library and Community are empty or thin right now. A rail that
    leads a reader to an empty page has spent the one thing this product is selling."""
    src = _app_source()
    labels = src.split("const NAV_LABELS = {", 1)[1].split("};", 1)[0]
    sidebar = src.split("const SIDEBAR = [", 1)[1].split("];", 1)[0]
    for route in ("radar", "globe", "exposure", "library", "community"):
        assert f"{route}:" not in labels, f"{route} is still in NAV_LABELS"
        assert f'"{route}"' not in sidebar, f"{route} is still on the sidebar"


def test_the_hidden_surfaces_are_still_addressable():
    """Off the rail, not bricked up. The Morning Brief and the Dashboard both link to the Radar and
    four surfaces link to library entries; dropping these from ROUTES would turn every one of those
    into a silent redirect to the Board, which is a worse failure than not advertising them."""
    src = _app_source()
    routes = src.split("const ROUTES = new Set(", 1)[1].split(");", 1)[0]
    for route in ("radar", "globe", "exposure", "library", "library-entry", "community", "trader"):
        assert f'"{route}"' in routes, f"{route} is unreachable even by URL"


def test_nothing_advertised_on_the_pricing_page_is_unreachable():
    """The specific bug this guards: `pricing.jsx` advertised N shadow portfolios as a paid
    entitlement while no route to that screen existed at all."""
    src = _app_source()
    labels = src.split("const NAV_LABELS = {", 1)[1].split("};", 1)[0]
    # Being in NAV_LABELS is what puts a route into ROUTES and into the command palette, both of
    # which are built from its keys, so this is the whole check.
    assert "portfolios:" in labels
    pricing = (APP_JSX.parent / "pricing.jsx").read_text()
    assert 'go: onNav && "portfolios"' in pricing, "the shadow portfolios line has no door"


def test_the_three_tiers_are_reader_caller_and_desk():
    from tradeos import billing
    names = {k: v["name"] for k, v in billing.PLANS.items()}
    assert names == {"free": "Reader", "retail": "Caller", "pro": "Desk"}
    assert [billing.PLANS[k]["price"] for k in ("free", "retail", "pro")] == [0, 19, 99]
    # The tier KEYS must not move: users.tier holds them and ENTITLEMENTS is keyed on them.
    assert [billing.PLANS[k]["tier"] for k in ("free", "retail", "pro")] == ["free", "retail", "pro"]


def test_the_news_window_is_a_preference_not_a_wall():
    """/api/news queried a fixed 72 hour window and rendered completely empty whenever ingestion
    had been stopped for longer than that, which on a laptop is any weekend. "There is no news" and
    "the machine that fetches news was off" are different statements."""
    from tradeos import db, news
    with db.connect() as conn:
        impossible = news.ranked_news_window(conn, hours=0, limit=5)
        assert impossible["items"], "a zero hour window must still show the most recent news"
        assert impossible["widened"] is True
        assert impossible["widened_note"] and impossible["newest"]

        # And it must not widen falsely: a filter that genuinely matches nothing stays empty.
        nothing = news.ranked_news_window(conn, category="no-such-category", hours=0, limit=5)
        assert nothing["items"] == [] and nothing["widened"] is False
