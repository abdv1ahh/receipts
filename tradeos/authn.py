"""Authentication, sessions, and entitlements (Slice 6, docs/threat-models/auth.md).

Demo-grade but real: argon2id hashing, invite-gated single-use registration, a breached-password
check against a local list, SHA-256-hashed session tokens, per-IP+per-account login rate limits,
and TOTP required for admin. Tier drives the free-tier delay server-side (never a client flag).
"""
from __future__ import annotations

import hashlib
import logging
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
    cur.execute(
        f"""INSERT INTO sessions (user_id, token_hash, expires_at, ip, ua)
            VALUES (%s, %s, now() + interval '{SESSION_HOURS} hours', %s, %s)""",
        (user_id, _hash_token(token), ip, ua),
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
             ip: str | None = None, ua: str | None = None) -> tuple[str, dict]:
    if is_weak_password(password):
        raise AuthError("password too short or too common")
    email = email.strip().lower()
    with conn.cursor() as cur:
        try:
            cur.execute("INSERT INTO users (email, password_hash) VALUES (%s, %s) RETURNING id, tier",
                        (email, hash_password(password)))
        except psycopg.errors.UniqueViolation:
            conn.rollback()
            raise AuthError("email already registered")
        uid, tier = cur.fetchone()
        cur.execute("UPDATE invites SET used_by = %s, used_at = now() WHERE code = %s AND used_by IS NULL",
                    (uid, invite_code))
        referred_by = None
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
    audit(conn, email, "register", email, {"referred_by": referred_by} if referred_by else None)
    return token, {"id": uid, "email": email, "tier": ("pro" if referred_by else tier)}


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
