"""Sign in with Google — the authorization-code flow (Phase 8).

**Status: implemented, config-gated, and NEVER EXERCISED against Google.** No credentials were
available while building it, so the live handshake is unverified. The parsing, validation and
linking logic is covered by offline tests against captured-shape payloads; the network round trip
is not. Treat that as a known gap, not as a working feature, until someone runs it with real
credentials — `sources.py` reports it as unconfigured for exactly this reason.

Five properties this has to get right, since an auth bug is the worst kind to ship:

  1. **`state` is one-time and server-side.** Stored as a row and *consumed* by deleting it, then
     checking that a row was actually deleted. A signed cookie can be replayed; a row cannot be
     deleted twice. This is the CSRF defence for the callback and there is no second one.

  2. **Identity is the provider's `sub`, never the email.** An address is mutable and reassignable
     — a corporate mailbox handed to a new employee would otherwise inherit the old employee's
     account. `sub` is stable for the life of the provider account.

  3. **`email_verified` must be true.** Without it, anyone who can set an unverified address at a
     provider could claim a matching local account.

  4. **Linking to an existing password account is refused.** If the asserted email already belongs
     to a local account that has no Google identity, this returns an error rather than silently
     merging. Automatic merging on email is a well-worn account-takeover path, and the safe
     resolution — prove control of the password account first — is a flow this does not have yet.

  5. **The ID token is read, not trusted blindly.** `iss`, `aud` and `exp` are all checked. The
     signature is NOT verified, and that is defensible *only* because the token is received
     directly from Google's token endpoint over TLS in a server-to-server call, which Google's own
     documentation states removes the need. If this token ever arrives by any other route — from
     the browser, from a cache, from a redirect fragment — signature verification becomes
     mandatory and this code is no longer sufficient.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import secrets
import time

import httpx
import psycopg

from . import authn

log = logging.getLogger("tradeos.oauth")

# RFC 6749 calls the second of these the "token endpoint". Any constant with TOKEN in its name
# trips ruff's S105 (hardcoded credential), and that rule is right to be suspicious of exactly this
# shape, so the name says what the endpoint DOES instead of suppressing the warning.
AUTHORIZE_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
EXCHANGE_ENDPOINT = "https://oauth2.googleapis.com/token"
ISSUERS = {"https://accounts.google.com", "accounts.google.com"}
STATE_TTL = 600           # seconds an unused state row stays valid
CLOCK_SKEW = 120          # tolerance on `exp`, for an honestly-wrong server clock


class OAuthError(Exception):
    """Raised for anything that should abort the flow. Messages are safe to show a user."""


def configured() -> bool:
    return bool(os.environ.get("GOOGLE_CLIENT_ID") and os.environ.get("GOOGLE_CLIENT_SECRET"))


def redirect_uri() -> str:
    """Must match a URI registered in the Google console exactly, including scheme and port."""
    base = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")
    return f"{base}/api/auth/google/callback"


# ------------------------------------------------------------------ pure: reading the ID token

def _b64url(segment: str) -> bytes:
    return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))


def decode_id_token(token: str) -> dict:
    """The claims out of a JWT, with no signature verification. See property 5 in the docstring for
    the precise circumstances under which that is acceptable — they are narrow."""
    try:
        _header, payload, _sig = token.split(".")
        return json.loads(_b64url(payload))
    except Exception as exc:
        raise OAuthError("could not read the identity token") from exc


def validate_claims(claims: dict, client_id: str, now: float | None = None) -> dict:
    """Check issuer, audience, expiry and email verification. Raises on anything unacceptable.

    Returns the fields worth keeping, so a caller cannot accidentally carry an unvalidated blob
    forward into the database."""
    now = now if now is not None else time.time()

    if claims.get("iss") not in ISSUERS:
        raise OAuthError("identity token came from an unexpected issuer")

    # `aud` may be a string or a list; both forms are legal and both are seen in practice.
    aud = claims.get("aud")
    audiences = aud if isinstance(aud, list) else [aud]
    if client_id not in audiences:
        raise OAuthError("identity token was issued for a different application")

    exp = claims.get("exp")
    if not isinstance(exp, (int, float)) or exp + CLOCK_SKEW < now:
        raise OAuthError("identity token has expired")

    sub = claims.get("sub")
    if not sub:
        raise OAuthError("identity token names no subject")

    # A truthy check, because Google sends this as a real bool but some providers send "true".
    verified = claims.get("email_verified")
    if verified is not True and str(verified).lower() != "true":
        raise OAuthError("that account's email address is not verified with the provider")

    email = (claims.get("email") or "").strip().lower()
    if not email:
        raise OAuthError("identity token carries no email address")

    return {"subject": str(sub), "email": email, "name": claims.get("name")}


# ------------------------------------------------------------------ DB: state, exchange, linking

def begin(conn: psycopg.Connection, redirect_to: str | None = None) -> str:
    """Create a one-time state and return the URL to send the browser to."""
    if not configured():
        raise OAuthError("Google sign-in is not configured on this deployment")
    state = secrets.token_urlsafe(32)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM oauth_states WHERE created_at < now() - make_interval(secs => %s)",
                    (STATE_TTL,))
        cur.execute("INSERT INTO oauth_states (state, provider, redirect_to) VALUES (%s,'google',%s)",
                    (state, (redirect_to or "/")[:200]))
    conn.commit()

    from urllib.parse import urlencode
    return AUTHORIZE_ENDPOINT + "?" + urlencode({
        "client_id": os.environ["GOOGLE_CLIENT_ID"],
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        # Ask the provider to re-confirm which account is being used rather than silently reusing
        # whichever session the browser already has — a shared machine otherwise signs in as
        # somebody else without anyone choosing to.
        "prompt": "select_account",
    })


def consume_state(conn: psycopg.Connection, state: str | None) -> str:
    """Delete the state row and confirm exactly one was deleted. Returns where to redirect.

    The whole CSRF defence is this function. A state that can be used twice is not a nonce, so the
    check is on `rowcount` rather than on a prior SELECT — a read-then-delete has a window."""
    if not state:
        raise OAuthError("sign-in request was missing its state")
    with conn.cursor() as cur:
        cur.execute("""DELETE FROM oauth_states
                        WHERE state = %s AND created_at > now() - make_interval(secs => %s)
                    RETURNING redirect_to""", (state, STATE_TTL))
        row = cur.fetchone()
    conn.commit()
    if not row:
        raise OAuthError("sign-in request expired or was already used")
    return row[0] or "/"


def exchange_code(code: str) -> dict:
    """Trade the authorization code for tokens. Server-to-server, over TLS, with the client secret.

    Any failure here is reported without the response body: a token-endpoint error can echo request
    parameters, and this request carries the client secret."""
    try:
        r = httpx.post(EXCHANGE_ENDPOINT, timeout=15, data={
            "code": code,
            "client_id": os.environ["GOOGLE_CLIENT_ID"],
            "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
            "redirect_uri": redirect_uri(),
            "grant_type": "authorization_code",
        })
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        log.warning("google token exchange failed (%s)", type(exc).__name__)
        raise OAuthError("could not complete sign-in with Google") from exc


def link_or_create(conn: psycopg.Connection, identity: dict, ip: str | None = None,
                   ua: str | None = None) -> tuple[str, dict]:
    """Resolve a validated identity to a session. Returns (session token, user).

    Three cases, in this order:
      1. the identity is already linked  -> sign in
      2. the email belongs to a local account with no link -> REFUSE (see property 4)
      3. otherwise -> create an account with an unusable password and link it
    """
    with conn.cursor() as cur:
        cur.execute("""SELECT o.user_id, u.email, u.tier, u.banned
                         FROM oauth_identities o JOIN users u ON u.id = o.user_id
                        WHERE o.provider = 'google' AND o.subject = %s""", (identity["subject"],))
        row = cur.fetchone()

        if row:
            uid, email, tier, banned = row
            if banned:
                raise OAuthError("this account is suspended")
            cur.execute("UPDATE oauth_identities SET last_login = now() "
                        "WHERE provider='google' AND subject=%s", (identity["subject"],))
            token = authn._create_session(cur, uid, ip, ua)
            conn.commit()
            authn.audit(conn, email, "oauth.login", email, {"provider": "google"})
            return token, {"id": uid, "email": email, "tier": tier}

        cur.execute("SELECT id FROM users WHERE email = %s", (identity["email"],))
        if cur.fetchone():
            # Never merge on an email match. The safe resolution is "sign in with your password,
            # then link Google from settings" — a flow that does not exist yet, so this is a dead
            # end on purpose rather than a convenient silent merge.
            raise OAuthError(
                "An account already exists for that email address. Sign in with your password "
                "first; linking Google to an existing account is not available yet.")

        # A password that cannot be guessed and is never shown to anyone. `password_hash` is NOT
        # NULL, and a random unusable value is a smaller change than making it nullable and having
        # to re-audit every path that reads it.
        cur.execute("INSERT INTO users (email, password_hash) VALUES (%s, %s) RETURNING id, tier",
                    (identity["email"], authn.hash_password(secrets.token_urlsafe(32))))
        uid, tier = cur.fetchone()
        cur.execute("""INSERT INTO oauth_identities (provider, subject, user_id, email, last_login)
                       VALUES ('google', %s, %s, %s, now())""",
                    (identity["subject"], uid, identity["email"]))
        token = authn._create_session(cur, uid, ip, ua)
    conn.commit()

    # Same pre-launch free access the password signup path grants, and it reverts identically the
    # moment a payment provider is configured. Duplicated deliberately rather than refactored:
    # `authn.register` also consumes an invite code, which this flow has no equivalent of.
    if not os.environ.get("STRIPE_SECRET_KEY"):
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET tier='pro' WHERE id=%s AND tier<>'admin'", (uid,))
        conn.commit()
        tier = "pro"

    authn.audit(conn, identity["email"], "oauth.register", identity["email"], {"provider": "google"})
    return token, {"id": uid, "email": identity["email"], "tier": tier}
