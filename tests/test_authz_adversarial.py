"""Adversarial authorization: two real accounts, one actually trying to reach the other's things.

**These are the only tests in the suite that touch a database.** Everything else is pure and
offline, and that is worth protecting — but a static check that a route mentions `user_id` asserts
the shape of the code, not the behaviour of the system, and the two disagree exactly when it
matters: when a guard exists, looks right, and is bypassable.

So this file signs in as Mallory and asks for Alice's things. No network is involved — the database
is the local container the rest of `make test` already depends on — and the whole file skips
cleanly when no database is reachable.

WHAT CHANGED WHEN THE RESEARCH PLANE WENT. The old file attacked trades, portfolios, watchlists,
the journal report, follows and notifications, because that was where the private data was. None of
those routes exists now. What is left is a product whose public surface is public ON PURPOSE, which
makes the boundary a different shape and, in one respect, a sharper one:

  what must stay PUBLIC    the board, a record, a chain, a card, /r/{handle}. A stranger has to be
                           able to check a caller without an account. Requiring one would be the
                           first thing taken on trust, which is the thing this product argues
                           against. A regression here is a guard added by mistake.
  what must stay PRIVATE   an account's own identity, another caller's publishing rights, and the
                           admin verification queue.
  what must stay IMPOSSIBLE  publishing into a chain that is not yours. This is the one that
                           cannot be undone: a call is sealed on write and a verdict is permanent,
                           so a caller_id a stranger can choose is not a data leak, it is a forged
                           entry in somebody else's permanent public record.

Every account and row it creates is removed in the fixture teardown.
"""
from __future__ import annotations

import secrets

import pytest

try:
    from fastapi.testclient import TestClient

    from tradeos import authn, db
    from tradeos.receipts import calls as receipts_calls
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
    """Alice holds a handle and has published. Mallory tries to publish into it. Both torn down."""
    from tradeos.app import app

    with db.connect() as conn:
        alice, mallory = _make_actor(app, conn), _make_actor(app, conn)
        handle = f"authz-{secrets.token_hex(6)}"
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO callers (handle, display_name, kind, user_id,
                                                jurisdiction_attested)
                           VALUES (%s, 'Alice', 'human', %s, true) RETURNING id""",
                        (handle, alice.uid))
            caller_id = cur.fetchone()[0]
        conn.commit()
        call = receipts_calls.publish(caller_id, {
            "symbol": "ABT", "direction": "up", "horizon_days": 7, "confidence": "low",
            "thesis": "a thesis long enough to be worth holding somebody to, forty plus characters",
        }, conn)

        yield {"alice": alice, "mallory": mallory, "caller_id": caller_id,
               "handle": handle, "call_id": call["id"]}

        conn.rollback()
        with conn.cursor() as cur:
            cur.execute("ALTER TABLE calls DISABLE TRIGGER calls_append_only_trg")
            cur.execute("DELETE FROM calls WHERE caller_id = %s", (caller_id,))
            cur.execute("ALTER TABLE calls ENABLE TRIGGER calls_append_only_trg")
            cur.execute("DELETE FROM callers WHERE id = %s", (caller_id,))
            for uid in (alice.uid, mallory.uid):
                # Neither `sessions.user_id` nor `invites.used_by` cascades, so both references go
                # first. The invite one was missing once: a torn-down user left an invites row
                # pointing at it and the DELETE aborted the whole transaction, leaving the accounts
                # behind. Three of them were found still sitting in the demo database days later.
                cur.execute("UPDATE invites SET used_by = NULL WHERE used_by = %s", (uid,))
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


# ------------------------------------------------------------------ the attempt that cannot be undone

def test_setup_actually_created_alices_record(actors):
    """If this fails the rest of the file is vacuously green, which is the failure mode of every
    negative test suite ever written."""
    assert actors["call_id"], "Alice's call was not published"
    r = actors["alice"].get("/api/callers/me")
    assert r.status_code == 200 and r.json()["caller"]["handle"] == actors["handle"]


def test_mallory_cannot_publish_into_alices_chain(actors):
    """THE one that cannot be taken back. A call is sealed on write and its verdict is permanent,
    so a caller_id a stranger can choose is not a data leak — it is a forged entry in somebody
    else's permanent public record, and no correction exists.

    The route derives the caller from the SESSION and takes no caller_id from the body. This sends
    one anyway, which `calls.validate` refuses outright as an unknown field rather than ignoring:
    a field silently dropped is a caller believing they said something they did not say.
    """
    r = actors["mallory"].post("/api/calls", {
        "caller_id": actors["caller_id"], "symbol": "ABT", "direction": "down",
        "horizon_days": 7, "confidence": "high",
        "thesis": "a forged call published into a record that belongs to somebody else entirely"})
    assert _denied(r), r.text

    with db.connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM calls WHERE caller_id = %s", (actors["caller_id"],))
        assert cur.fetchone()[0] == 1, "Mallory published into Alice's chain"


def test_mallory_cannot_claim_a_handle_that_is_taken(actors):
    r = actors["mallory"].post("/api/callers", {
        "handle": actors["handle"], "display_name": "Not Alice", "kind": "human",
        "jurisdiction_attested": True})
    assert _denied(r), r.text
    with db.connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT user_id FROM callers WHERE handle = %s", (actors["handle"],))
        assert cur.fetchone()[0] == actors["alice"].uid, "the handle changed hands"


def test_my_caller_is_the_callers_own(actors):
    """`/api/callers/me` resolves through the session. Mallory holds no handle and must be told
    that, not handed Alice's."""
    r = actors["mallory"].get("/api/callers/me")
    assert actors["handle"] not in r.text
    assert r.status_code != 200 or not r.json().get("caller")


def test_a_non_admin_cannot_reach_the_verification_queue(actors):
    """`_require_admin` returns the USER on success and None on failure — getting that backwards
    serves admin data to everyone, silently. It has happened once in this project."""
    r = actors["mallory"].get("/api/admin/callers/pending")
    assert _denied(r), r.text
    r = actors["mallory"].post("/api/admin/callers/1/verify", {"decision": "verified"})
    assert _denied(r), r.text


def test_a_forged_session_cookie_is_rejected(actors):
    """Sessions are stored as a hash, so a guessed or stolen-looking token must not resolve."""
    from tradeos.app import app

    forged = TestClient(app)
    forged.cookies.set("tos_session", secrets.token_urlsafe(32))
    assert forged.get("/api/auth/me").json().get("user") is None
    assert _denied(forged.get("/api/callers/me"))
    assert _denied(forged.post("/api/calls", json={
        "symbol": "ABT", "direction": "up", "horizon_days": 7, "confidence": "low",
        "thesis": "a call published on a session token that was never issued by this server"}))


# ------------------------------------------------------------------ and what must stay open

def test_the_record_answers_a_stranger_with_no_account(actors):
    """A guard added here would be a regression, not a fix. The product's argument is that a reader
    can check a caller without taking anything on trust, and an account with us would be the first
    thing taken on trust. Every one of these must answer a client holding no cookie at all."""
    from tradeos.app import app

    anon = TestClient(app)
    for path in ("/api/board",
                 f"/api/receipts/{actors['handle']}",
                 f"/api/receipts/{actors['handle']}/chain",
                 f"/api/receipts/{actors['handle']}/verify",
                 f"/api/calls/{actors['call_id']}",
                 "/api/receipts/methodology",
                 f"/r/{actors['handle']}",
                 f"/api/card/receipt/{actors['handle']}.svg"):
        r = anon.get(path)
        assert r.status_code in (200, 429), f"{path} refused a stranger: {r.status_code}"


def test_no_public_surface_discloses_an_account_address(actors):
    """A handle is public and an email address is not. They are joined one table apart."""
    from tradeos.app import app

    anon = TestClient(app)
    for path in ("/api/board", f"/api/receipts/{actors['handle']}",
                 f"/api/calls/{actors['call_id']}", f"/r/{actors['handle']}"):
        r = anon.get(path)
        if r.status_code == 200:
            assert "@test.invalid" not in r.text, f"{path} leaked an account address"
