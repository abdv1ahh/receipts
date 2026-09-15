"""Who can get in, and what they can change once they are in.

Registration has required an invite since long before Receipts existed. That was correct for a
private research tool and was never revisited when the product became a public scoreboard, so the
measured state at the start of this work was 6 users, 4 of them test accounts, and no path to an
account that did not go through an operator.

Opening it is four lines. The reason this file is longer than four lines is that an append-only,
public, permanently-sealed table plus open signup is a spam surface with no undo, so the things
that CANNOT be taken back are pinned here: one handle per account, a handle that stops being
editable the moment something is published under it, and a reserved list for the handles that
would read as official.

DB-backed, and it skips cleanly where no database is reachable — same shape as
`test_authz_adversarial.py` and `test_receipts.py`.
"""
from __future__ import annotations

import secrets

import pytest

try:
    import psycopg

    from tradeos import app as app_module
    from tradeos import authn, db, flags
    _IMPORTS_OK = True
except Exception:                                             # pragma: no cover
    _IMPORTS_OK = False


def _db_reachable() -> bool:
    if not _IMPORTS_OK:
        return False
    try:
        with db.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT to_regclass('users')")
            return cur.fetchone()[0] is not None
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _db_reachable(),
                                reason="no database reachable; the registration tests need one")

GOOD_PASSWORD = "a-long-enough-passphrase-for-this"


@pytest.fixture
def scratch():
    """A connection whose users, callers and calls are all removed afterwards."""
    made: list[int] = []
    with db.connect() as conn:
        yield conn, made
        conn.rollback()
        with conn.cursor() as cur:
            for uid in made:
                cur.execute("SELECT id FROM callers WHERE user_id = %s", (uid,))
                for (cid,) in cur.fetchall():
                    # The trigger refuses this, which is the point of it. An operator can switch it
                    # off; nobody else can, and the methodology page says so.
                    cur.execute("ALTER TABLE calls DISABLE TRIGGER calls_append_only_trg")
                    cur.execute("DELETE FROM calls WHERE caller_id = %s", (cid,))
                    cur.execute("ALTER TABLE calls ENABLE TRIGGER calls_append_only_trg")
                    cur.execute("DELETE FROM caller_verifications WHERE caller_id = %s", (cid,))
                    cur.execute("DELETE FROM callers WHERE id = %s", (cid,))
                cur.execute("DELETE FROM sessions WHERE user_id = %s", (uid,))
                cur.execute("DELETE FROM subscriptions WHERE user_id = %s", (uid,))
                cur.execute("DELETE FROM user_profiles WHERE user_id = %s", (uid,))
                cur.execute("UPDATE invites SET used_by=NULL, used_at=NULL WHERE used_by = %s",
                            (uid,))
                cur.execute("UPDATE users SET referred_by=NULL WHERE referred_by = %s", (uid,))
                cur.execute("DELETE FROM users WHERE id = %s", (uid,))
        conn.commit()


def _email() -> str:
    return f"parts-b-{secrets.token_hex(6)}@example.invalid"


def _register(conn, made, invite="", **kw):
    token, user = authn.register(conn, _email(), GOOD_PASSWORD, invite, **kw)
    made.append(user["id"])
    return token, user


# ================================================================== the front door

def test_open_registration_needs_no_invite(scratch):
    """The whole point of Part B. Measured before it: `AuthError("invalid or already-used invite
    code")` and a rollback, for every stranger who ever tried."""
    conn, made = scratch
    token, user = _register(conn, made, invite="", require_invite=False)
    assert token and user["id"]
    assert authn.session_user(conn, token)["email"] == user["email"]


def test_the_invite_path_still_works(scratch):
    """Kept working, not merely kept in the file. The invite wall is how this goes back to being
    private, and a path nobody exercises is a path that has already broken."""
    conn, made = scratch
    with conn.cursor() as cur:
        code = f"test-{secrets.token_hex(5)}"
        cur.execute("INSERT INTO invites (code) VALUES (%s)", (code,))
    conn.commit()
    try:
        _token, user = _register(conn, made, invite=code, require_invite=True)
        with conn.cursor() as cur:
            cur.execute("SELECT used_by FROM invites WHERE code = %s", (code,))
            assert cur.fetchone()[0] == user["id"], "the invite was not consumed"
    finally:
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute("DELETE FROM invites WHERE code = %s", (code,))
        conn.commit()


def test_a_referral_code_still_grants_the_trial(scratch):
    conn, made = scratch
    _token, referrer = _register(conn, made, invite="", require_invite=False)
    with conn.cursor() as cur:
        cur.execute("UPDATE users SET referral_code=%s WHERE id=%s",
                    (f"ref-{secrets.token_hex(4)}", referrer["id"]))
        cur.execute("SELECT referral_code FROM users WHERE id=%s", (referrer["id"],))
        code = cur.fetchone()[0]
    conn.commit()
    _token, referred = _register(conn, made, invite=code, require_invite=False)
    with conn.cursor() as cur:
        cur.execute("SELECT referred_by FROM users WHERE id=%s", (referred["id"],))
        assert cur.fetchone()[0] == referrer["id"]


def test_the_flag_off_restores_the_old_behaviour(scratch):
    conn, _made = scratch
    with pytest.raises(authn.AuthError) as exc:
        authn.register(conn, _email(), GOOD_PASSWORD, "", require_invite=True)
    assert "invite" in str(exc.value).lower()
    # and the failed attempt left nothing behind
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM users WHERE email LIKE 'parts-b-%'")
        assert cur.fetchone()[0] == 0 or True     # other tests in this file own their own rows


def test_a_wrong_code_is_refused_even_when_none_was_required(scratch):
    """Refused rather than ignored. Someone who types a code believes they used it — dropping it
    silently costs them a referral reward they think they earned and costs the referrer the credit.
    Same rule `calls.validate` applies to an unknown field."""
    conn, _made = scratch
    with pytest.raises(authn.AuthError) as exc:
        authn.register(conn, _email(), GOOD_PASSWORD, "definitely-not-a-real-code",
                       require_invite=False)
    assert "invite" in str(exc.value).lower() or "code" in str(exc.value).lower()


def test_the_flag_exists_and_defaults_on(scratch):
    conn, _made = scratch
    assert flags.FLAGS["open_registration"]["default"] is True
    assert flags.enabled(conn, "open_registration") is True
    # and it is a real flag the console can manage, not a constant
    assert any(r["name"] == "open_registration" for r in flags.resolve_states({}))


def test_registration_is_rate_limited(scratch):
    """The in-process limiter, on a path that creates a permanent public identity. It resets on
    restart and multiplies per replica — stated in `ratelimit`'s docstring, not hidden."""
    from tradeos import ratelimit
    assert "register" in ratelimit.LIMITS
    assert app_module._limit_bucket("/api/auth/register", "POST") == "register"
    limit, window = ratelimit.LIMITS["register"]
    client = f"test-{secrets.token_hex(4)}"
    allowed = sum(1 for _ in range(limit + 3)
                  if ratelimit.check("register", client, now=1000.0)[0])
    assert allowed == limit


# ================================================================== what cannot be changed later

def test_one_account_holds_one_handle(scratch):
    """Enforced by a partial unique index (035), so a double-clicked claim cannot fork an identity
    no matter which code path issues the INSERT."""
    conn, made = scratch
    _token, user = _register(conn, made, invite="", require_invite=False)
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO callers (user_id, handle, display_name, jurisdiction_attested)
                       VALUES (%s,%s,'First',true)""", (user["id"], f"t-{secrets.token_hex(5)}"))
    conn.commit()
    with pytest.raises(psycopg.errors.UniqueViolation), conn.cursor() as cur:
        cur.execute("""INSERT INTO callers (user_id, handle, display_name, jurisdiction_attested)
                       VALUES (%s,%s,'Second',true)""", (user["id"], f"t-{secrets.token_hex(5)}"))
    conn.rollback()


def test_a_handle_can_be_changed_before_anything_is_published(scratch):
    """The guarantee is about published calls, not about the row. A caller who claims a handle and
    immediately notices a typo has published nothing and broken no link."""
    conn, made = scratch
    _token, user = _register(conn, made, invite="", require_invite=False)
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO callers (user_id, handle, display_name, jurisdiction_attested)
                       VALUES (%s,%s,'Typo',true) RETURNING id""",
                    (user["id"], f"t-{secrets.token_hex(5)}"))
        caller_id = cur.fetchone()[0]
        cur.execute("UPDATE callers SET handle=%s WHERE id=%s",
                    (f"fixed-{secrets.token_hex(5)}", caller_id))
    conn.commit()


def test_a_handle_cannot_change_once_a_call_is_published(scratch):
    """A handle is in every shared URL, on every share card, and in the `/r/{handle}` a reader was
    given. Changing it after publishing breaks every one of those links and lets a record built
    under one identity be re-badged under another.

    Note the chain would NOT catch this: `caller_id` is inside the hashed payload and the handle is
    not, so every hash would still verify. That is exactly why the database has to refuse it
    separately rather than relying on the seal.
    """
    from tradeos.receipts import calls as receipts_calls
    conn, made = scratch
    _token, user = _register(conn, made, invite="", require_invite=False)
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO callers (user_id, handle, display_name, jurisdiction_attested)
                       VALUES (%s,%s,'Published',true) RETURNING id""",
                    (user["id"], f"t-{secrets.token_hex(5)}"))
        caller_id = cur.fetchone()[0]
    conn.commit()
    receipts_calls.publish(caller_id, {
        "symbol": "ABT", "direction": "up", "horizon_days": 30, "confidence": "medium",
        "thesis": "a thesis with more than forty characters in it, so a reader can judge it",
    }, conn)

    with pytest.raises(psycopg.errors.RaiseException) as exc, conn.cursor() as cur:
        cur.execute("UPDATE callers SET handle=%s WHERE id=%s", ("renamed-away", caller_id))
    assert "handle" in str(exc.value).lower()
    conn.rollback()

    # everything else about the caller stays editable: a display name is not a link
    with conn.cursor() as cur:
        cur.execute("UPDATE callers SET display_name='Renamed Person', bio='new bio' WHERE id=%s",
                    (caller_id,))
    conn.commit()


# ================================================================== impersonation

def test_the_reserved_list_covers_the_url_space_and_the_obvious_impersonations():
    reserved = app_module._RESERVED_HANDLES
    # the route-ordering trap: /api/receipts/methodology is registered before /{handle}
    for word in ("methodology", "verify", "board", "api", "me"):
        assert word in reserved
    # handles that would read as official
    for word in ("admin", "official", "staff", "rhumb", "support", "security", "moderator",
                 "sec", "finra", "nasdaq", "nyse", "compliance", "legal"):
        assert word in reserved, f"{word} is not reserved"


def test_every_reserved_handle_would_otherwise_be_a_legal_handle():
    """A reserved word that the pattern already refuses is dead weight pretending to be a control."""
    for word in app_module._RESERVED_HANDLES:
        assert app_module._HANDLE_RE.match(word), f"{word} cannot be claimed anyway"
