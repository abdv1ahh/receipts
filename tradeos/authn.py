"""Authentication, sessions, and entitlements (Slice 6, docs/threat-models/auth.md).

Demo-grade but real: argon2id hashing, invite-gated single-use registration, a breached-password
check against a local list, SHA-256-hashed session tokens, per-IP+per-account login rate limits,
and TOTP required for admin. Tier drives the free-tier delay server-side (never a client flag).
"""
from __future__ import annotations

import hashlib
import logging
import os
import secrets

import psycopg
import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from psycopg.types.json import Json

log = logging.getLogger("tradeos.authn")
_ph = PasswordHasher()  # argon2id defaults
SESSION_HOURS = 24
LOGIN_LIMIT = 10          # attempts per key per window
LOGIN_WINDOW_MIN = 15

# A small demo stand-in for a top-100k breached-password list (a drop-in replacement in prod).
# The check runs locally so a password is never sent anywhere.
_COMMON = {
    "password", "password1", "password123", "123456", "12345678", "123456789", "qwerty",
    "qwertyuiop", "letmein", "welcome", "welcome1", "admin", "admin123", "iloveyou",
    "monkey", "dragon", "abc123", "111111", "000000", "trustno1", "sunshine", "princess",
    "football", "baseball", "superman", "changeme", "passw0rd", "tradeos", "tradeos123",
}


class AuthError(RuntimeError):
    pass


# ------------------------------------------------------------------ passwords

def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(stored_hash: str, password: str) -> bool:
    try:
        return _ph.verify(stored_hash, password)
    except (VerifyMismatchError, Exception):
        return False


def is_weak_password(password: str) -> bool:
    """True if the password is too short or on the breached/common list."""
    return len(password) < 10 or password.lower() in _COMMON


# ------------------------------------------------------------------ tokens / sessions

def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _create_session(cur, user_id: int, ip: str | None, ua: str | None) -> str:
    token = secrets.token_urlsafe(32)
    # `make_interval` with a bound parameter rather than an interval literal built by f-string.
    # SESSION_HOURS is a module constant and was never injectable, but a session lifetime is not
    # somewhere to leave a string-built query, and this removes the question entirely.
    cur.execute(
        """INSERT INTO sessions (user_id, token_hash, expires_at, ip, ua)
           VALUES (%s, %s, now() + make_interval(hours => %s), %s, %s)""",
        (user_id, _hash_token(token), SESSION_HOURS, ip, ua),
    )
    return token


def _expire_trial_if_lapsed(cur, conn, user_id: int, tier: str) -> str:
    """Lazy trial enforcement: a lapsed 'trialing' subscription downgrades the user to free on read,
    so a referral (or Stripe) trial expires on its own without a running cron."""
    cur.execute("SELECT 1 FROM subscriptions WHERE user_id=%s AND status='trialing' AND current_period_end < now()",
                (user_id,))
    if cur.fetchone():
        cur.execute("UPDATE users SET tier='free' WHERE id=%s AND tier<>'admin'", (user_id,))
        cur.execute("UPDATE subscriptions SET status='canceled', plan='free', updated_at=now() WHERE user_id=%s",
                    (user_id,))
        conn.commit()
        return "free"
    return tier


def session_user(conn: psycopg.Connection, token: str | None) -> dict | None:
    if not token:
        return None
    with conn.cursor() as cur:
        cur.execute(
            """SELECT u.id, u.email, u.tier, u.handle FROM sessions s JOIN users u ON u.id = s.user_id
               WHERE s.token_hash = %s AND s.expires_at > now() AND NOT u.banned""",
            (_hash_token(token),),
        )
        r = cur.fetchone()
        if not r:
            return None
        uid, email, tier, handle = r
        if tier in ("retail", "pro"):
            tier = _expire_trial_if_lapsed(cur, conn, uid, tier)
    return {"id": uid, "email": email, "tier": tier, "handle": handle}


def logout(conn: psycopg.Connection, token: str | None) -> None:
    if not token:
        return
    with conn.cursor() as cur:
        cur.execute("DELETE FROM sessions WHERE token_hash = %s", (_hash_token(token),))
    conn.commit()


# ------------------------------------------------------------------ rate limiting

def _rate_limited(cur, key: str | None) -> bool:
    if not key:
        return False
    cur.execute(
        "SELECT count(*) FROM login_attempts WHERE key = %s AND at > now() - make_interval(mins => %s)",
        (key, LOGIN_WINDOW_MIN),
    )
    return cur.fetchone()[0] >= LOGIN_LIMIT


def _record_attempt(cur, key: str | None) -> None:
    if key:
        cur.execute("INSERT INTO login_attempts (key, at) VALUES (%s, now())", (key,))


# ------------------------------------------------------------------ audit

def audit(conn: psycopg.Connection, actor: str | None, action: str, obj: str | None = None, detail: dict | None = None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO audit_log (actor, action, object, detail) VALUES (%s, %s, %s, %s)",
            (actor, action, obj, Json(detail) if detail is not None else None),
        )
    conn.commit()


# ------------------------------------------------------------------ register / login

def register(conn: psycopg.Connection, email: str, password: str, invite_code: str,
             ip: str | None = None, ua: str | None = None,
             require_invite: bool = True) -> tuple[str, dict]:
    """Create an account and return (session token, user).

    `require_invite` DEFAULTS TO TRUE, which is fail-closed on purpose: this function is called
    from one route that reads the `open_registration` flag, and any future caller that forgets to
    pass it gets the private-product behaviour rather than silently opening the door.

    Three cases, and the middle one is the interesting one:

      a code is given and it resolves    consumed as a single-use invite, or credited as another
                                         user's referral. Works whether or not one was required.
      a code is given and it does not    REFUSED, even when none was required. Someone who types a
                                         code believes they used it; dropping it silently costs
                                         them a referral reward they think they earned and costs
                                         the referrer their credit. Same rule `calls.validate`
                                         applies to a field it does not recognise.
      no code is given                   allowed when `require_invite` is False, refused otherwise.
    """
    if is_weak_password(password):
        raise AuthError("password too short or too common")
    email = email.strip().lower()
    invite_code = (invite_code or "").strip()
    if not invite_code and require_invite:
        # Checked before the INSERT rather than after it. The old order created the user, failed
        # the invite lookup, and relied on `conn.rollback()` to undo it — which worked, but meant
        # the ordinary "no code" path ran a password hash and a write for nothing.
        raise AuthError("an invite code is required to create an account right now")
    with conn.cursor() as cur:
        try:
            cur.execute("INSERT INTO users (email, password_hash) VALUES (%s, %s) RETURNING id, tier",
                        (email, hash_password(password)))
        except psycopg.errors.UniqueViolation as exc:
            conn.rollback()
            raise AuthError("email already registered") from exc
        uid, tier = cur.fetchone()
        referred_by = None
        if invite_code:
            cur.execute("UPDATE invites SET used_by = %s, used_at = now() "
                        "WHERE code = %s AND used_by IS NULL", (uid, invite_code))
            if cur.rowcount != 1:
                # not a single-use invite — it may be another user's reusable referral code
                cur.execute("SELECT id FROM users WHERE referral_code = %s", (invite_code,))
                ref = cur.fetchone()
                if not ref:
                    conn.rollback()
                    raise AuthError("invalid or already-used invite code")
                referred_by = ref[0]
                cur.execute("UPDATE users SET referred_by = %s WHERE id = %s", (referred_by, uid))
        token = _create_session(cur, uid, ip, ua)
    conn.commit()
    if referred_by is not None:
        _grant_trial(conn, uid, days=14)   # welcome reward for a referred signup (lazily expiring)
    # Pre-launch free access: until a real payment provider is configured, every new signup gets full
    # Pro access at no charge (the pricing page stays visible in test mode). This auto-reverts to the
    # normal free default the moment STRIPE_SECRET_KEY is set, so switching on paid billing at launch
    # needs no code change — just the key.
    launch_free = not os.environ.get("STRIPE_SECRET_KEY")
    if launch_free and referred_by is None:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET tier='pro' WHERE id=%s AND tier<>'admin'", (uid,))
        conn.commit()
    audit(conn, email, "register", email, {"referred_by": referred_by} if referred_by else None)
    effective_tier = "pro" if (referred_by or launch_free) else tier
    return token, {"id": uid, "email": email, "tier": effective_tier}


def login(conn: psycopg.Connection, email: str, password: str, totp_code: str | None = None,
          ip: str | None = None, ua: str | None = None) -> tuple[str, dict]:
    email = email.strip().lower()
    with conn.cursor() as cur:
        if _rate_limited(cur, ip) or _rate_limited(cur, email):
            _record_attempt(cur, ip)
            conn.commit()
            raise AuthError("too many attempts; try again later")
        _record_attempt(cur, ip)
        _record_attempt(cur, email)
        conn.commit()
        cur.execute("SELECT id, password_hash, tier, totp_secret, banned FROM users WHERE email = %s", (email,))
        row = cur.fetchone()
    if not row or not verify_password(row[1], password):
        raise AuthError("invalid credentials")  # uniform: never distinguish which field failed
    uid, _h, tier, totp_secret, banned = row
    if banned:                                   # only reached with a correct password; honest signal
        raise AuthError("this account has been suspended")
    # TOTP required for admin; enforced whenever a secret is set
    if tier == "admin" and not totp_secret:
        raise AuthError("invalid credentials")  # admin without MFA configured cannot log in
    if totp_secret:
        if not totp_code or not pyotp.TOTP(totp_secret).verify(totp_code, valid_window=1):
            raise AuthError("invalid credentials")
    with conn.cursor() as cur:
        token = _create_session(cur, uid, ip, ua)
    conn.commit()
    return token, {"id": uid, "email": email, "tier": tier}


# ------------------------------------------------------------------ invites / admin

def create_invite(conn: psycopg.Connection, actor_user_id: int | None) -> str:
    code = secrets.token_urlsafe(9)
    with conn.cursor() as cur:
        cur.execute("INSERT INTO invites (code, created_by) VALUES (%s, %s)", (code, actor_user_id))
    conn.commit()
    audit(conn, str(actor_user_id), "create_invite", code)
    return code


def new_totp_secret() -> str:
    return pyotp.random_base32()


# ------------------------------------------------------------------ referrals

def get_or_create_referral_code(conn: psycopg.Connection, user_id: int) -> str:
    with conn.cursor() as cur:
        cur.execute("SELECT referral_code FROM users WHERE id=%s", (user_id,))
        r = cur.fetchone()
        if r and r[0]:
            return r[0]
        for _ in range(5):
            code = secrets.token_urlsafe(6)
            try:
                cur.execute("UPDATE users SET referral_code=%s WHERE id=%s", (code, user_id))
                conn.commit()
                return code
            except psycopg.errors.UniqueViolation:
                conn.rollback()
    raise AuthError("could not allocate a referral code")


def referral_stats(conn: psycopg.Connection, user_id: int) -> dict:
    code = get_or_create_referral_code(conn, user_id)
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM users WHERE referred_by=%s", (user_id,))
        n = cur.fetchone()[0]
    return {"code": code, "referred": n}


def _grant_trial(conn: psycopg.Connection, user_id: int, days: int = 14) -> None:
    """Grant/extend a Pro trial. Expiry is enforced lazily by session_user, so no cron is needed."""
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO subscriptions (user_id, plan, status, provider, current_period_end, updated_at)
               VALUES (%s,'pro','trialing','referral', now() + make_interval(days => %s), now())
               ON CONFLICT (user_id) DO UPDATE SET plan='pro', status='trialing', provider='referral',
                   current_period_end = GREATEST(subscriptions.current_period_end, now() + make_interval(days => %s)),
                   updated_at=now()""",
            (user_id, days, days),
        )
        cur.execute("UPDATE users SET tier='pro' WHERE id=%s AND tier='free'", (user_id,))
    conn.commit()


# ------------------------------------------------------------------ entitlements

FREE_DELAY_HOURS = 48


def delay_hours(tier: str | None) -> int:
    """Free (and unauthenticated) users see signals delayed; paid tiers see them live."""
    return 0 if tier in ("retail", "pro", "admin") else FREE_DELAY_HOURS


# ------------------------------------------------ email verification and password reset (post-9)
#
# Two capabilities that behave identically and differ only in what redeeming them does. Four
# properties hold for both, and every one of them is the difference between a feature and a hole:
#
#   * the token is stored HASHED, so reading the table grants nothing;
#   * it is SINGLE-USE, enforced by an UPDATE that only matches an unused row and checking that a
#     row was actually matched — a read-then-mark has a window where two requests both win;
#   * it EXPIRES, in hours not days;
#   * requesting one NEVER reveals whether the address exists.

VERIFY_TTL_HOURS = 24
RESET_TTL_HOURS = 1
TOKEN_REQUEST_LIMIT = 5          # per address per window, to stop an inbox being used as a weapon


def issue_token(conn: psycopg.Connection, user_id: int, purpose: str, ttl_hours: int) -> str:
    """Mint a single-use capability and return the RAW token — the only moment it exists in the
    clear. The caller's one job is to put it in an email and nowhere else.

    Any unused token of the same purpose is invalidated first: a second "reset my password" click
    should not leave the first link live, or a stolen-then-abandoned email keeps working.
    """
    token = secrets.token_urlsafe(32)
    with conn.cursor() as cur:
        cur.execute("UPDATE auth_tokens SET used_at = now() "
                    "WHERE user_id=%s AND purpose=%s AND used_at IS NULL", (user_id, purpose))
        cur.execute(
            """INSERT INTO auth_tokens (user_id, purpose, token_hash, expires_at)
               VALUES (%s, %s, %s, now() + make_interval(hours => %s))""",
            (user_id, purpose, _hash_token(token), ttl_hours))
    conn.commit()
    return token


def consume_token(conn: psycopg.Connection, token: str | None, purpose: str) -> int | None:
    """Redeem a token, returning its user id, or None if it is unknown, expired or already used.

    The single-use guarantee is the `used_at IS NULL` in the WHERE clause plus the RETURNING: two
    concurrent redemptions cannot both match, because the second sees the row already stamped.
    """
    if not token:
        return None
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE auth_tokens SET used_at = now()
                WHERE token_hash = %s AND purpose = %s
                  AND used_at IS NULL AND expires_at > now()
            RETURNING user_id""",
            (_hash_token(token), purpose))
        row = cur.fetchone()
    conn.commit()
    return row[0] if row else None


def _token_requests_recent(cur, email: str) -> bool:
    cur.execute(
        """SELECT count(*) FROM auth_tokens t JOIN users u ON u.id = t.user_id
            WHERE u.email = %s AND t.created_at > now() - interval '1 hour'""", (email,))
    return cur.fetchone()[0] >= TOKEN_REQUEST_LIMIT


def start_email_verification(conn: psycopg.Connection, email: str) -> str | None:
    """A verification token for this address, or None if there is nothing to verify.

    None covers both "no such account" and "already verified". The CALLER must answer identically
    either way — see the note in the route.
    """
    email = (email or "").strip().lower()
    with conn.cursor() as cur:
        cur.execute("SELECT id, email_verified_at FROM users WHERE email = %s", (email,))
        row = cur.fetchone()
        if not row or row[1] is not None or _token_requests_recent(cur, email):
            return None
    return issue_token(conn, row[0], "verify_email", VERIFY_TTL_HOURS)


def confirm_email(conn: psycopg.Connection, token: str | None) -> dict:
    uid = consume_token(conn, token, "verify_email")
    if not uid:
        return {"ok": False, "error": "that link is invalid, expired, or already used"}
    with conn.cursor() as cur:
        cur.execute("UPDATE users SET email_verified_at = now() WHERE id = %s AND email_verified_at IS NULL",
                    (uid,))
    conn.commit()
    audit(conn, None, "email.verified", str(uid))
    return {"ok": True}


def start_password_reset(conn: psycopg.Connection, email: str) -> str | None:
    """A reset token, or None when there is no account (or the address is being hammered)."""
    email = (email or "").strip().lower()
    with conn.cursor() as cur:
        cur.execute("SELECT id, banned FROM users WHERE email = %s", (email,))
        row = cur.fetchone()
        if not row or row[1] or _token_requests_recent(cur, email):
            return None
    return issue_token(conn, row[0], "reset_password", RESET_TTL_HOURS)


def complete_password_reset(conn: psycopg.Connection, token: str | None, new_password: str) -> dict:
    """Set a new password and sign out everywhere.

    **Every other session is destroyed.** A reset is what someone does when they believe the
    account is compromised, and leaving the attacker's session alive would make the reset
    ceremonial. It also costs the legitimate user one re-login, which is the right trade.
    """
    if is_weak_password(new_password):
        return {"ok": False, "error": "password too short or too common"}
    uid = consume_token(conn, token, "reset_password")
    if not uid:
        return {"ok": False, "error": "that link is invalid, expired, or already used"}
    with conn.cursor() as cur:
        cur.execute("UPDATE users SET password_hash = %s WHERE id = %s", (hash_password(new_password), uid))
        cur.execute("DELETE FROM sessions WHERE user_id = %s", (uid,))
        # A reset proves control of the mailbox, which is exactly what verification asks for.
        cur.execute("UPDATE users SET email_verified_at = coalesce(email_verified_at, now()) WHERE id = %s",
                    (uid,))
    conn.commit()
    audit(conn, None, "password.reset", str(uid))
    return {"ok": True}
