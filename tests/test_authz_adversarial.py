"""Adversarial authorization: two real accounts, one actually trying to read the other's data.

**These are the only tests in the suite that touch a database.** Everything else is pure and
offline, and that is worth protecting — but the brief asks for authorization "tested adversarially
with automated tests", and a static check that a route mentions `user_id` is not adversarial. It
asserts the shape of the code, not the behaviour of the system. The two disagree exactly when it
matters: when a guard exists, looks right, and is bypassable.

So this file signs in as Mallory and asks for Alice's things. No network is involved — the database
is the local container the rest of `make test` already depends on — and the whole file skips
cleanly when no database is reachable, so it cannot turn a green suite red on a machine that
deliberately has none.

Every account and row it creates is removed in the fixture teardown.
"""
from __future__ import annotations

import secrets

import pytest

try:
    from fastapi.testclient import TestClient

    from tradeos import authn, db
    _IMPORTS_OK = True
except Exception:                                             # pragma: no cover
    _IMPORTS_OK = False


def _db_reachable() -> bool:
    if not _IMPORTS_OK:
        return False
    try:
        with db.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _db_reachable(),
                                reason="no database reachable; adversarial authz tests need one")


# ------------------------------------------------------------------ fixtures

class _Actor:
    def __init__(self, client: TestClient, uid: int, email: str):
        self.client, self.uid, self.email = client, uid, email

    def get(self, path):
        return self.client.get(path)

    def post(self, path, json=None):
        return self.client.post(path, json=json or {})

    def patch(self, path, json=None):
        return self.client.patch(path, json=json or {})

    def delete(self, path):
        return self.client.delete(path)


def _make_actor(app, conn) -> _Actor:
    """A real account with a real session, created directly rather than through the signup route —
    registration consumes an invite code, and this file is testing authorization, not signup."""
    email = f"authz-{secrets.token_hex(6)}@test.invalid"
    with conn.cursor() as cur:
        cur.execute("INSERT INTO users (email, password_hash, tier) VALUES (%s,%s,'pro') RETURNING id",
                    (email, authn.hash_password(secrets.token_urlsafe(24))))
        uid = cur.fetchone()[0]
        token = authn._create_session(cur, uid, "127.0.0.1", "pytest")
    conn.commit()
    client = TestClient(app)
    client.cookies.set("tos_session", token)
    return _Actor(client, uid, email)


@pytest.fixture(scope="module")
def actors():
    """Alice owns things. Mallory tries to read them. Both are torn down."""
    from tradeos.app import app

    with db.connect() as conn:
        alice, mallory = _make_actor(app, conn), _make_actor(app, conn)
        # Alice's private objects, created through the API so they are exactly what a real user has.
        r = alice.post("/api/trades", {"symbol": "SECRET", "direction": "long", "status": "open",
                                       "entry_price": 100, "stop_price": 90, "target_price": 130,
                                       "reason_entry": "alice private note", "is_public": False})
        alice_trade = r.json().get("id")
        r = alice.post("/api/portfolios", {"name": "Alice private", "kind": "manual"})
        alice_portfolio = r.json().get("id")
        alice.post("/api/watchlist/ALICEONLY")

        yield {"alice": alice, "mallory": mallory,
               "trade": alice_trade, "portfolio": alice_portfolio}

        with conn.cursor() as cur:
            for uid in (alice.uid, mallory.uid):
                # `sessions.user_id` has no ON DELETE CASCADE, so the session rows go first.
                cur.execute("DELETE FROM sessions WHERE user_id = %s", (uid,))
                cur.execute("DELETE FROM users WHERE id = %s", (uid,))
        conn.commit()


def _denied(resp) -> bool:
    """Refusal, in any of the shapes this codebase legitimately uses.

    A 404 counts, and is often the *better* answer — telling a stranger "403, that exists but is
    not yours" confirms the object. What must never count is a 200 carrying the data.
    """
    if resp.status_code in (401, 403, 404):
        return True
    if resp.status_code != 200:
        return True
    body = resp.json()
    return body.get("found") is False or body.get("authenticated") is False or "error" in body


# ------------------------------------------------------------------ the attempts

def test_setup_actually_created_alices_objects(actors):
    """If this fails the rest of the file is vacuously green, which is the failure mode of every
    negative test suite ever written."""
    assert actors["trade"], "Alice's trade was not created"
    assert actors["portfolio"], "Alice's portfolio was not created"
    own = actors["alice"].get(f"/api/trades/{actors['trade']}").json()
    assert own["found"] is True and own["owner"] is True


def test_mallory_cannot_read_alices_private_trade(actors):
    r = actors["mallory"].get(f"/api/trades/{actors['trade']}")
    assert _denied(r), r.text
    assert "alice private note" not in r.text


def test_mallory_cannot_read_the_world_context_of_alices_trade(actors):
    """Stricter than the trade itself: the snapshot is ranked by the owner's personal relevance, so
    it discloses their country, currency and watchlist."""
    r = actors["mallory"].get(f"/api/trades/{actors['trade']}/context")
    assert _denied(r), r.text


def test_mallory_cannot_read_the_ai_analysis_of_alices_private_trade(actors):
    r = actors["mallory"].get(f"/api/trades/{actors['trade']}/analysis")
    assert _denied(r), r.text


def test_mallory_cannot_read_the_chart_image_of_alices_trade(actors):
    r = actors["mallory"].get(f"/api/trades/{actors['trade']}/image")
    assert r.status_code != 200 or not r.content, r.status_code


def test_mallory_cannot_edit_alices_trade(actors):
    r = actors["mallory"].patch(f"/api/trades/{actors['trade']}", {"symbol": "PWNED", "direction": "long"})
    assert _denied(r), r.text
    still = actors["alice"].get(f"/api/trades/{actors['trade']}").json()
    assert still["trade"]["symbol"] == "SECRET", "Mallory modified Alice's trade"


def test_mallory_cannot_delete_alices_trade(actors):
    r = actors["mallory"].delete(f"/api/trades/{actors['trade']}")
    assert _denied(r), r.text
    assert actors["alice"].get(f"/api/trades/{actors['trade']}").json()["found"] is True


def test_mallorys_similar_trades_never_reach_alices_journal(actors):
    """The cohort finder searches a journal. It must search the CALLER's, never the owner's."""
    r = actors["mallory"].get(f"/api/trades/{actors['trade']}/similar")
    assert _denied(r) or "SECRET" not in r.text, r.text


def test_mallory_cannot_read_alices_portfolio(actors):
    r = actors["mallory"].get(f"/api/portfolios/{actors['portfolio']}")
    assert _denied(r), r.text
    assert "Alice private" not in r.text


def test_mallory_cannot_delete_alices_portfolio(actors):
    """Asserted on the EFFECT, not the response. This route answers `{"removed": false}` with a
    200 — correct, and identical to what a nonexistent id returns, which is the right amount to
    tell a stranger. The first version of this test read that as a success and failed; the object
    surviving is the property that actually matters."""
    actors["mallory"].delete(f"/api/portfolios/{actors['portfolio']}")
    survived = actors["alice"].get(f"/api/portfolios/{actors['portfolio']}")
    assert survived.status_code == 200 and "Alice private" in survived.text, \
        "Mallory deleted Alice's portfolio"


def test_watchlists_are_not_shared(actors):
    """B-22 was exactly this: one shared list addressable by a query parameter."""
    r = actors["mallory"].get("/api/watchlist")
    assert "ALICEONLY" not in r.text, "Mallory sees Alice's watchlist"


def test_the_journal_report_is_computed_over_the_callers_own_journal(actors):
    r = actors["mallory"].get("/api/journal/report")
    assert "SECRET" not in r.text
    assert r.json().get("report", {}).get("n_total", 0) == 0, "Mallory's report counted Alice's trades"


def test_performance_is_the_callers_own(actors):
    r = actors["mallory"].get("/api/performance")
    assert r.json().get("total", 0) == 0, "Mallory's performance counted Alice's trades"


def test_an_anonymous_caller_gets_none_of_it(actors):
    """No cookie at all — the case that matters most, and the one a logged-in developer never
    exercises by hand."""
    from tradeos.app import app

    anon = TestClient(app)
    for path in (f"/api/trades/{actors['trade']}",
                 f"/api/trades/{actors['trade']}/context",
                 f"/api/trades/{actors['trade']}/analysis",
                 f"/api/portfolios/{actors['portfolio']}",
                 "/api/watchlist", "/api/journal/report", "/api/performance",
                 "/api/follows", "/api/notifications", "/api/alert-prefs"):
        r = anon.get(path)
        assert _denied(r), f"anonymous read succeeded on {path}: {r.text[:200]}"


def test_a_non_admin_cannot_reach_the_admin_surface(actors):
    """`_require_admin` returns the USER on success and None on failure — getting that backwards
    serves admin data to everyone, silently. It has happened once in this project."""
    for path in ("/api/admin/users", "/api/admin/watchlist-accounts", "/api/admin/audit",
                 "/api/admin/reports", "/api/admin/flags"):
        r = actors["mallory"].get(path)
        assert _denied(r), f"non-admin reached {path}: {r.text[:200]}"


def test_the_public_surface_leaks_nothing_user_scoped(actors):
    """These answer anyone. Nothing a signed-in user owns may appear in them."""
    from tradeos.app import app

    anon = TestClient(app)
    for path in ("/api/public/live", "/api/public/walkthrough", "/api/public/frame?country=AE",
                 "/api/ledger"):
        r = anon.get(path)
        assert r.status_code in (200, 429), f"{path} -> {r.status_code}"
        if r.status_code == 200:
            assert "SECRET" not in r.text and "ALICEONLY" not in r.text
            assert "alice private note" not in r.text
            assert "@test.invalid" not in r.text


def test_a_forged_session_cookie_is_rejected(actors):
    """Sessions are stored as a hash, so a guessed or stolen-looking token must not resolve."""
    from tradeos.app import app

    forged = TestClient(app)
    forged.cookies.set("tos_session", secrets.token_urlsafe(32))
    assert _denied(forged.get("/api/journal/report"))
    assert forged.get("/api/auth/me").json().get("user") is None
