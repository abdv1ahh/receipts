"""TradeOSS API.

Slice 1 seeded the honesty surface (/api/feeds). Slice 2 added /api/activity (merged,
knowable_time-ordered disclosure per issuer). Slice 3 adds the signal surface:
  /api/clusters            — the dashboard feed of convergence clusters (medium+ by default)
  /api/clusters/{issuer}   — full cluster detail: every contributing event and its weight
  /api/definitions         — the public, versioned methodology (definition is product)
and serves the React dashboard build at / when present.
"""
from __future__ import annotations

import logging
import os
import re
import secrets
from pathlib import Path

from fastapi import BackgroundTasks, Cookie, FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from psycopg import sql
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.gzip import GZipMiddleware

from . import (
    authn,
    config,
    db,
    flags,
    mail,
    oauth,
    ratelimit,
)
from .receipts import calls as receipts_calls
from .receipts import card as receipts_card
from .receipts import chain as receipts_chain
from .receipts import page as receipts_page
from .receipts import record as receipts_record
from .receipts import scoring as receipts_scoring
from .receipts import universe as receipts_universe
from .receipts import verification as receipts_verification

# One sentence, one place. It appears on every public Receipts surface and on the share card, and
# a second copy of it would be the one that drifted. The wording is deliberate: this platform
# MEASURES public statements, which is what keeps it an analytics tool rather than an advisory
# service. Chairman of the Board Resolution No. (10/R.M) of 2025 applies by AUDIENCE location
# rather than by creator location, and SEC Rule 206(4)-1 treats a public scoreboard of named
# advisers as edging toward a third party rating, so neither the copy nor the ranking may suggest
# that a position here recommends anybody.
RECEIPTS_DISCLAIMER = ("This platform measures publicly stated market calls. It is not investment "
                       "advice, it is not a recommendation, and no position on the board is an "
                       "endorsement of any person. Past performance does not predict future "
                       "results.")

SESSION_COOKIE = "tos_session"
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "false").lower() == "true"  # true behind TLS in prod


class RegisterReq(BaseModel):
    email: str
    password: str
    # Optional on the wire, because registration is open by default. Still honoured when supplied:
    # a referral code credits the referrer and grants the new account its trial. The server decides
    # whether one is REQUIRED (the `open_registration` flag), so the client cannot opt out of the
    # invite wall by omitting the field.
    invite_code: str = ""


class LoginReq(BaseModel):
    email: str
    password: str
    totp_code: str | None = None
class EmailReq(BaseModel):
    email: str


class TokenReq(BaseModel):
    token: str


class ResetConfirmReq(BaseModel):
    token: str
    password: str
def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(SESSION_COOKIE, token, httponly=True, secure=COOKIE_SECURE,
                        samesite="lax", max_age=authn.SESSION_HOURS * 3600, path="/")

log = logging.getLogger("tradeos.api")

# Optional error tracking (build-plan 7.4): active only when a DSN is set AND the SDK is present,
# so it adds no hard dependency to the demo image.
if os.environ.get("SENTRY_DSN"):
    try:
        import sentry_sdk
        sentry_sdk.init(dsn=os.environ["SENTRY_DSN"], traces_sample_rate=0.0)
        log.info("Sentry error tracking enabled")
    except Exception:
        log.warning("SENTRY_DSN set but sentry_sdk is not installed; error tracking disabled")

app = FastAPI(title="TradeOSS", docs_url=None, redoc_url=None, openapi_url=None)

CALIBRATION_PENDING = "Backtested calibration pending"  # until Slice 4 (rule: no premature certainty)
_BUCKET_RANK = {"low": 0, "medium": 1, "high": 2}
MAX_IMAGE_BYTES = 8 * 1024 * 1024
_ALLOWED_IMAGE = {"image/png", "image/jpeg", "image/webp"}
_extract_calls: list[float] = []
# ---- user-uploaded trade screenshots: re-encoded, opaque-named, served through an authed route
UPLOADS_DIR = Path(os.environ.get("UPLOADS_DIR", str(Path(__file__).parent.parent / "uploads")))
_IMG_KEY = re.compile(r"[0-9a-f]{32}\.png")
# A chart screenshot is a PNG, a JPEG, a WebP or a GIF. Nothing else needs to be decodable.
#
# Pillow ships decoders for PSD, FITS, PCF, BDF and a long tail of others, and several of those
# have a history of memory-safety bugs — the version this repo pinned until Phase 9 had a
# known out-of-bounds write and a memory-corruption issue, both reachable by uploading a crafted
# PSD, because `Image.open` sniffs the format from the bytes and the caller never said which
# formats it wanted. Upgrading fixes the known ones; refusing to decode formats the product has no
# use for is what keeps the next one out of reach.
_ALLOWED_IMAGE_FORMATS = {"PNG", "JPEG", "WEBP", "GIF"}
_CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; "
        "form-action 'self'")


# Extra origins allowed to make state-changing requests. Only ever set in development, where the
# Vite dev server lives on another port; empty in production, so the check stays strict.
_DEV_ORIGINS = {o.strip() for o in os.environ.get("DEV_ORIGINS", "").split(",") if o.strip()}


def _origin_ok(origin: str, host: str | None) -> bool:
    from urllib.parse import urlparse
    return urlparse(origin).netloc == host or origin in _DEV_ORIGINS


# Paths a stranger can reach without a session. Everything else is behind authentication, which
# is its own limit — an attacker without an account cannot spend an account's allowance.
_PUBLIC_PREFIXES = ("/api/public/", "/api/ledger", "/api/receipts", "/api/board", "/r/",
                    "/api/card/receipt/", "/api/calls/")
# Routes that may spend model quota. Gemini's free daily allowance is shared by every user, so one
# script exhausting it silences the AI surfaces for everybody until midnight UTC.
_MODEL_PATHS = ("/api/assistant", "/api/analyze-chart", "/api/extract-tickers")
# Anything that can cause an email to be sent, or that guesses at a token.
_AUTH_TOKEN_PATHS = ("/api/auth/verify/", "/api/auth/reset/")
# Creating an account. Registration is open now, and an account is upstream of a caller handle and
# of permanent rows on a public board, so it gets a bucket tighter than the publish one.
_REGISTER_PATHS = ("/api/auth/register",)
# Publishing seals a row that can never be deleted, so a runaway script does permanent damage
# rather than recoverable damage. It gets its own bucket for that reason and not for load.
_PUBLISH_PATHS = ("/api/calls",)


def _limit_bucket(path: str, method: str = "GET") -> str | None:
    # The method matters for exactly one of these. `/api/calls` is a publish when it is a POST and
    # a public read of one call when it is a GET, and putting a public read in the publish bucket
    # would let twenty page views an hour exhaust a limit meant for writes.
    if method == "POST" and path.startswith(_PUBLISH_PATHS):
        return "publish"
    if path.startswith(_REGISTER_PATHS):
        return "register"
    if path.startswith(_PUBLIC_PREFIXES):
        return "public"
    if path.startswith(_MODEL_PATHS):
        return "model"
    if path.startswith(_AUTH_TOKEN_PATHS):
        return "auth_token"
    if path.endswith("/image") or path.endswith("/chart-analysis"):
        return "upload"
    return None


# Compression, from Starlette — no new dependency, and `requirements.txt` is untouched.
#
# Added on a measurement rather than as hygiene. The public record page's Verify button downloads
# every sealed call so the browser can hash them, which for our own 323-call record is 350KB of
# mostly prose. On a throttled phone that was 2.5 SECONDS of transfer before the flagship
# interaction of the product said anything, out of 3.4s for the whole click. The page itself goes
# from 111KB to 12KB.
#
# Production already compresses at the edge (`deploy/Caddyfile`: `encode gzip zstd`), and Caddy
# passes an upstream `Content-Encoding` through rather than re-encoding it, so this changes nothing
# there. What it buys is that the number above is the one EVERY deployment gets, including a bare
# `docker compose up` with no proxy in front, rather than a property of one reverse-proxy config
# that a later deploy could drop without anyone noticing.
#
# 800 bytes because below roughly that the header and the CPU cost more than the saving, and the
# research surfaces are full of small JSON responses that would pay it for nothing.
#
# LEVEL 6, NOT STARLETTE'S DEFAULT OF 9. Measured on the three payloads that matter: the chain JSON
# 24,182 vs 23,733 bytes (1.3ms vs 1.7ms), the record page 12,149 vs 11,620 (0.4ms vs 1.5ms). Level
# 9 spends roughly three times the CPU on the page for four percent fewer bytes, which on a
# throttled connection is around one millisecond of transfer.
#
# There is NO content-type filter, which means an already-compressed response is re-compressed:
# measured, `/api/card/receipt/{handle}.png` pays 0.8ms to save 5.7% on a 58KB image. That endpoint
# is the link preview, so every social scraper hits it — the number is recorded here rather than
# left to intuition, because it is small enough not to be worth a subclass of the middleware and
# large enough that someone will eventually wonder. Revisit if card traffic ever becomes real
# volume; Starlette offers no content-type option, so the fix would be a `GZipResponder` subclass.
app.add_middleware(GZipMiddleware, minimum_size=800, compresslevel=6)


@app.middleware("http")
async def harden(request: Request, call_next):
    # CSRF: refuse a cross-origin state-changing request (belt-and-braces with SameSite=Lax)
    if request.method in ("POST", "PUT", "DELETE", "PATCH"):
        origin = request.headers.get("origin")
        if origin and not _origin_ok(origin, request.headers.get("host")):
            return JSONResponse({"error": "cross-origin request refused"}, status_code=403)

    # Rate limiting, before any work is done. `ratelimit` is in-process and says so — see its
    # docstring for what that does and does not buy.
    bucket = _limit_bucket(request.url.path, request.method)
    if bucket:
        ok, retry = ratelimit.check(bucket, ratelimit.client_key(request))
        if not ok:
            return JSONResponse(
                {"error": "too many requests", "retry_after_seconds": retry},
                status_code=429, headers={"Retry-After": str(retry)})
    # One id per request, echoed to the client and stamped on every log line for it, so a failure
    # the user reports can be traced end to end. Never derived from user input.
    rid = secrets.token_hex(8)
    request.state.request_id = rid
    try:
        response = await call_next(request)
    except Exception:  # uniform error shape, never a stack trace to the client
        log.exception("unhandled error on %s %s [rid=%s]", request.method, request.url.path, rid)
        return JSONResponse({"error": "internal error", "request_id": rid}, status_code=500,
                            headers={"X-Request-Id": rid})
    response.headers["X-Request-Id"] = rid
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = _CSP
    if COOKIE_SECURE:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


@app.get("/health")
def health() -> dict:
    return {"ok": True}


# --------------------------------------------------------------------------- auth

@app.post("/api/auth/register")
def auth_register(req: RegisterReq, request: Request, response: Response) -> dict:
    try:
        with db.connect() as conn:
            if not flags.enabled(conn, "registration"):
                response.status_code = 403
                return {"error": "registration is temporarily closed"}
            token, user = authn.register(conn, req.email, req.password, req.invite_code,
                                         ip=request.client.host if request.client else None,
                                         ua=request.headers.get("user-agent"),
                                         require_invite=not flags.enabled(conn,
                                                                          "open_registration"))
    except authn.AuthError as exc:
        response.status_code = 400
        return {"error": str(exc)}
    _set_session_cookie(response, token)
    return {"user": user}


@app.get("/api/auth/registration")
def registration_state() -> dict:
    """Whether an account can be created, and whether a code is needed. Public and unauthenticated.

    This exists because the auth screen used to print the words "Invite-only." as a hardcoded
    string. Once the flag can be flipped at runtime that sentence is a guess, and a signup screen
    that guesses wrong about its own requirements is the worst place in the product to be wrong.
    """
    with db.connect() as conn:
        on = flags.enabled(conn, "registration")
        open_signup = flags.enabled(conn, "open_registration")
    return {
        "open": on,
        "invite_required": on and not open_signup,
        # Said here rather than only in the docs. With no SMTP configured there is no email
        # verification flow at all, so a reader of any public record is entitled to know that the
        # only thing behind a handle is an address nobody has confirmed.
        "email_verification": False,
        "note": ("Anyone can create an account." if on and open_signup
                 else "An invite or referral code is required." if on
                 else "Registration is closed."),
    }


@app.post("/api/auth/login")
def auth_login(req: LoginReq, request: Request, response: Response) -> dict:
    try:
        with db.connect() as conn:
            token, user = authn.login(conn, req.email, req.password, req.totp_code,
                                      ip=request.client.host if request.client else None,
                                      ua=request.headers.get("user-agent"))
    except authn.AuthError as exc:
        response.status_code = 401
        return {"error": str(exc)}
    _set_session_cookie(response, token)
    return {"user": user}


# ------------------------------------------ email verification and password reset (post-Phase 9)
#
# The two flows the ten-phase brief never asked for and that would have hurt a real user first.
#
# ONE RULE GOVERNS BOTH REQUEST ROUTES: the response is identical whether or not the address has an
# account. Otherwise this endpoint becomes a free membership oracle — point it at a list of
# addresses and learn which ones are customers. The token is emailed and never returned here; if
# mail is unconfigured the request still answers the same way, because telling a stranger about the
# server's mail configuration is also an answer.

_ENUMERATION_SAFE = ("If that address has an account, a message is on its way. "
                     "The link expires and can be used once.")

# EVERYTHING runs after the response, as a background task — the lookup, the token, the send.
#
# Not for latency: for the timing side channel. Both routes answer with identical wording so the
# response cannot reveal whether the address has an account, and then the response *time* answers
# it anyway, because only a real address does any work. Measured before this change: 0.06s for a
# real address against 0.01s for a fake one, and that was already after moving only the SMTP call
# out. With the whole operation deferred, the handler does the same nothing in both cases.
#
# The cost is that a failure in here reaches the logs and not the caller. That was already true by
# design — these routes are not allowed to report what happened.


def _deliver(email: str, kind: str) -> None:
    """Issue and send, off the request path. Never raises into the server."""
    try:
        with db.connect() as conn:
            if kind == "verify":
                token = authn.start_email_verification(conn, email)
                if token:
                    mail.send(email, mail.VERIFY_SUBJECT, mail.verify_body(token))
            else:
                token = authn.start_password_reset(conn, email)
                if token:
                    mail.send(email, mail.RESET_SUBJECT, mail.reset_body(token))
    except Exception as exc:
        log.warning("%s delivery failed (%s)", kind, type(exc).__name__)


@app.post("/api/auth/verify/request")
def auth_verify_request(req: EmailReq, background: BackgroundTasks) -> dict:
    background.add_task(_deliver, (req.email or "").strip().lower(), "verify")
    return {"sent": True, "message": _ENUMERATION_SAFE}


@app.post("/api/auth/verify/confirm")
def auth_verify_confirm(req: TokenReq, response: Response) -> dict:
    with db.connect() as conn:
        out = authn.confirm_email(conn, req.token)
    if not out["ok"]:
        response.status_code = 400
    return out


@app.post("/api/auth/reset/request")
def auth_reset_request(req: EmailReq, background: BackgroundTasks) -> dict:
    background.add_task(_deliver, (req.email or "").strip().lower(), "reset")
    return {"sent": True, "message": _ENUMERATION_SAFE}


@app.post("/api/auth/reset/confirm")
def auth_reset_confirm(req: ResetConfirmReq, response: Response) -> dict:
    """Redeeming this signs out every session on the account, including this one."""
    with db.connect() as conn:
        out = authn.complete_password_reset(conn, req.token, req.password)
    if not out["ok"]:
        response.status_code = 400
    else:
        response.delete_cookie(SESSION_COOKIE, path="/")
    return out


# ------------------------------------------------------------------ Sign in with Google (Phase 8)
#
# Config-gated and NEVER EXERCISED against Google — no credentials were available while building
# it. See the module docstring in `oauth.py`; the validation logic is tested offline, the live
# handshake is not.

@app.get("/api/auth/google/start")
def auth_google_start(response: Response, redirect_to: str | None = None):
    with db.connect() as conn:
        try:
            url = oauth.begin(conn, redirect_to)
        except oauth.OAuthError as exc:
            response.status_code = 503
            return {"error": str(exc), "configured": oauth.configured()}
    return RedirectResponse(url, status_code=302)


@app.get("/api/auth/google/callback")
def auth_google_callback(request: Request, response: Response, code: str | None = None,
                         state: str | None = None, error: str | None = None):
    """Where Google sends the browser back. Every failure lands the user on a page that says what
    went wrong rather than on a JSON blob — this is a browser navigation, not an API call."""
    # A CODE, never a message. Two reasons, both learned from this landing on a page that renders it:
    # anyone can hand a victim a link to our real login screen carrying arbitrary text, and text we
    # supply is trusted-looking there — so the client owns the wording and only recognises a fixed
    # set. And `str(exc)` on an internal error has no business travelling through a URL bar into a
    # browser; it is logged here instead, where whoever needs it can actually see it.
    def _fail(code: str, detail: str | None = None):
        if detail:
            log.warning("google sign-in failed (%s): %s", code, detail)
        return RedirectResponse(f"/auth?auth_error={code}", status_code=302)

    if error:
        return _fail("cancelled")
    if not code:
        return _fail("no_code")

    with db.connect() as conn:
        try:
            destination = oauth.consume_state(conn, state)       # one-time; this is the CSRF check
            tokens = oauth.exchange_code(code)
            claims = oauth.decode_id_token(tokens.get("id_token") or "")
            identity = oauth.validate_claims(claims, os.environ.get("GOOGLE_CLIENT_ID", ""))
            token, _user = oauth.link_or_create(
                conn, identity,
                ip=request.client.host if request.client else None,
                ua=request.headers.get("user-agent"))
        except oauth.OAuthError as exc:
            return _fail("failed", detail=str(exc))

    redirect = RedirectResponse(destination, status_code=302)
    _set_session_cookie(redirect, token)
    return redirect


@app.post("/api/auth/logout")
def auth_logout(response: Response, tos_session: str | None = Cookie(None)) -> dict:
    with db.connect() as conn:
        authn.logout(conn, tos_session)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@app.get("/api/auth/me")
def auth_me(tos_session: str | None = Cookie(None)) -> dict:
    with db.connect() as conn:
        return {"user": authn.session_user(conn, tos_session)}
_TRADE_COLS = ("id", "user_id", "symbol", "entity_id", "asset_class", "direction", "status",
               "entry_price", "exit_price", "stop_price", "target_price", "size", "size_unit",
               "timeframe", "strategy", "reason_entry", "reason_exit", "confidence",
               "expected_outcome", "opened_on", "closed_on", "image_path", "is_public",
               "created_at", "updated_at")
# Composed once with psycopg.sql rather than joined into an f-string. The values in _TRADE_COLS
# are fixed internal identifiers and were never attacker-controlled, but "safe because I read it"
# is exactly the guarantee that decays — Identifier() makes it structural, and it is what lets
# ruff's S608 stay ON so a future f-string here is a lint failure rather than a review question.
_TRADE_COL_SQL = sql.SQL(", ").join(sql.Identifier(c) for c in _TRADE_COLS)
_ASSET = {"equity", "crypto", "forex", "option", "future", "other"}
_DIR = {"long", "short"}
_STATUS = {"planned", "open", "closed"}
_UNIT = {"shares", "contracts", "usd", "units", "lots"}
def _require_admin(conn, token: str | None, response: Response) -> dict | None:
    """Return the admin user, or set 401/403 and return None. Admin is a real tier gated behind TOTP
    at login (authn.login), so this is the same identity that MFA'd in — no separate admin flag."""
    user = authn.session_user(conn, token)
    if not user:
        response.status_code = 401
        return None
    if user["tier"] != "admin":
        response.status_code = 403
        return None
    return user
def _og_tags(*, title: str, description: str, path: str, image_path: str,
             image_type: str = "image/png") -> str:
    """The Open Graph and Twitter block, built once for every share page.

    EVERY URL HERE IS ABSOLUTE, and that is the defect this exists to fix. `og:image` on both share
    pages pointed at a RELATIVE path -- `/api/card/receipt/x.svg` -- and the protocol requires an
    absolute URL, so Facebook, X, LinkedIn, Slack and Discord all declined to resolve it against
    the page. Compounding it, the image was an SVG, which no major platform renders as a preview.
    Either defect alone produces a bare text link, both were present, and the mechanism the whole
    growth model rests on had therefore never worked once.

    `og:image:width` and `:height` are declared because a scraper that knows the dimensions before
    it fetches can lay out the card immediately; without them some platforms render a small
    thumbnail on first sight and only upgrade it after a later crawl, which is the one impression
    that matters shown at its worst.

    Built in one place so the two pages cannot drift -- `/s/{symbol}` had this bug because
    `/r/{handle}` did, copied verbatim.
    """
    base = config.public_base_url()
    e = receipts_card._xml_escape
    return (f'<meta property="og:type" content="website">\n'
            f'<meta property="og:site_name" content="{e(config.brand_name())}">\n'
            f'<meta property="og:title" content="{e(title)}">\n'
            f'<meta property="og:description" content="{e(description)}">\n'
            f'<meta property="og:url" content="{e(base + path)}">\n'
            f'<meta property="og:image" content="{e(base + image_path)}">\n'
            f'<meta property="og:image:type" content="{e(image_type)}">\n'
            f'<meta property="og:image:width" content="{receipts_card.WIDTH}">\n'
            f'<meta property="og:image:height" content="{receipts_card.HEIGHT}">\n'
            f'<meta property="og:image:alt" content="{e(title)}">\n'
            f'<meta name="twitter:card" content="summary_large_image">\n'
            f'<meta name="twitter:title" content="{e(title)}">\n'
            f'<meta name="twitter:description" content="{e(description)}">\n'
            f'<meta name="twitter:image" content="{e(base + image_path)}">\n'
            f'<meta name="twitter:image:alt" content="{e(title)}">\n'
            f'<link rel="canonical" href="{e(base + path)}">')
class CallerReq(BaseModel):
    handle: str
    display_name: str
    bio: str | None = None
    audience_url: str | None = None
    # Not optional and not defaulted to True. A caller states that their own regulatory and
    # registration status in their own jurisdiction is their responsibility. This platform measures
    # public statements; it does not license anyone to make them, and it must not read as though it
    # does. See docs and the disclaimer copy.
    jurisdiction_attested: bool = False


class VerifyStartReq(BaseModel):
    method: str


class VerifyConfirmReq(BaseModel):
    evidence_url: str


class VerifyReviewReq(BaseModel):
    approve: bool


class CallReq(BaseModel):
    symbol: str
    direction: str
    horizon_days: int
    confidence: str
    thesis: str


_HANDLE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,29}$")

# Words the URL space already spends. `GET /api/receipts/methodology` is registered before
# `GET /api/receipts/{handle}`, so a caller holding that handle could never have their record
# served: the route would answer with the methodology payload and the record page would render a
# caller that is not there. The rest are reserved before the same trap can be set for them, and
# because a record at /r/admin reads as an official one.
# Two groups, for two different reasons.
#
# THE URL SPACE. `GET /api/receipts/methodology` is registered before `GET /api/receipts/{handle}`,
# so a caller holding that handle could never have their record served: the route would answer with
# the methodology payload and the record page would render a caller that is not there.
#
# IMPERSONATION. Registration is open now, so the first person to type `sec` or `nasdaq` gets a
# public, permanent, sealed record at `/r/sec` that reads as an official one — and the handle
# becomes unchangeable the moment they publish under it (migration 037), so it cannot be taken back
# later either. Cheap to reserve in advance; impossible to reclaim afterwards. This list is not a
# trademark policy and does not pretend to be one: it covers the words whose misuse would mislead a
# reader about WHO IS SPEAKING, which is the one thing this product sells.
_RESERVED_HANDLES = frozenset({
    # the URL space
    "methodology", "verify", "board", "api", "me", "new", "settings", "record", "publish",
    "call", "calls", "callers", "card", "site", "health", "static", "assets",
    # this product speaking
    "admin", "official", "staff", "rhumb", "tradeos", "tradeoss", "team", "moderator", "mod",
    "root", "system", "security", "billing", "press", "news", "info", "contact", "legal",
    "compliance", "support", "help", "about", "login", "logout", "signup", "account",
    # regulators and exchanges, which is the impersonation a market record invites
    "sec", "finra", "cftc", "fca", "esma", "sipc", "nyse", "nasdaq", "cboe", "lse",
})


def _caller_for_user(conn, user_id: int) -> dict | None:
    with conn.cursor() as cur:
        cur.execute("SELECT handle FROM callers WHERE user_id = %s", (user_id,))
        row = cur.fetchone()
    return receipts_record.caller(row[0], conn) if row else None


@app.post("/api/callers")
def claim_handle(req: CallerReq, response: Response, tos_session: str | None = Cookie(None)) -> dict:
    with db.connect() as conn:
        user = authn.session_user(conn, tos_session)
        if not user:
            response.status_code = 401
            return {"error": "sign in first"}

        handle = req.handle.strip().lower()
        if not _HANDLE_RE.match(handle):
            response.status_code = 400
            return {"error": "a handle is 2 to 30 characters, lower case letters, digits and "
                             "hyphens, starting with a letter or a digit."}
        if handle in _RESERVED_HANDLES:
            response.status_code = 400
            return {"error": f"the handle {handle} is reserved."}
        if not req.jurisdiction_attested:
            # Refused rather than defaulted. The attestation is the whole reason the column exists.
            response.status_code = 400
            return {"error": "you have to confirm that your own regulatory and registration status "
                             "in your jurisdiction is your responsibility."}
        audience = (req.audience_url or "").strip()
        if audience and not audience.lower().startswith("https://"):
            # HTTPS only, and refused rather than coerced. This value is rendered as the `href` of
            # a link on a PUBLIC record page, and React escapes attribute values without
            # restricting the scheme, so `javascript:` would survive to an anchor anybody could
            # click. `receipts.verification.confirm` applies the identical rule to its evidence
            # URL; this one was the only user-supplied URL in the feature that reached an href
            # without it.
            response.status_code = 400
            return {"error": "the link to your audience has to be an https address."}
        if _caller_for_user(conn, user["id"]):
            response.status_code = 409
            return {"error": "this account already holds a record."}

        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM callers WHERE lower(handle) = %s", (handle,))
            if cur.fetchone():
                response.status_code = 409
                return {"error": f"the handle {handle} is taken."}
            cur.execute("""INSERT INTO callers (user_id, handle, display_name, bio, audience_url,
                                                jurisdiction_attested)
                           VALUES (%s,%s,%s,%s,%s,true) RETURNING id""",
                        (user["id"], handle, req.display_name.strip()[:80],
                         (req.bio or "").strip()[:500] or None, audience or None))
            cur.fetchone()
        conn.commit()
        return {"caller": _caller_for_user(conn, user["id"])}


@app.get("/api/callers/me")
def my_caller(response: Response, tos_session: str | None = Cookie(None)) -> dict:
    with db.connect() as conn:
        user = authn.session_user(conn, tos_session)
        if not user:
            response.status_code = 401
            return {"error": "sign in first"}
        caller = _caller_for_user(conn, user["id"])
        published = 0
        if caller:
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM calls WHERE caller_id = %s", (caller["id"],))
                published = cur.fetchone()[0]
        return {"caller": caller,
                # How many calls exist, so the publish surface can decide whether a panel about
                # PROVING an identity makes sense yet. `summary.counts` cannot answer it: a caller
                # with only unscoreable calls has zero in every scoreable bucket.
                "published": published,
                "summary": receipts_record.summary(caller["id"], conn) if caller else None,
                # Served rather than typed into the client. A second copy of this sentence is the
                # one that would drift, and it is the sentence that keeps this an analytics tool.
                "disclaimer": RECEIPTS_DISCLAIMER}


@app.post("/api/callers/verify/start")
def verify_start(req: VerifyStartReq, response: Response,
                 tos_session: str | None = Cookie(None)) -> dict:
    with db.connect() as conn:
        user = authn.session_user(conn, tos_session)
        if not user:
            response.status_code = 401
            return {"error": "sign in first"}
        caller = _caller_for_user(conn, user["id"])
        if not caller:
            response.status_code = 404
            return {"error": "claim a handle first."}
        out = receipts_verification.start(caller["id"], req.method, conn)
        if "error" in out:
            response.status_code = 400
        return out


@app.post("/api/callers/verify/confirm")
def verify_confirm(req: VerifyConfirmReq, response: Response,
                   tos_session: str | None = Cookie(None)) -> dict:
    with db.connect() as conn:
        user = authn.session_user(conn, tos_session)
        if not user:
            response.status_code = 401
            return {"error": "sign in first"}
        caller = _caller_for_user(conn, user["id"])
        if not caller:
            response.status_code = 404
            return {"error": "claim a handle first."}
        out = receipts_verification.confirm(caller["id"], req.evidence_url, conn)
        if "error" in out:
            response.status_code = 400
        return out


@app.get("/api/admin/callers/pending")
def admin_pending_verifications(response: Response,
                                tos_session: str | None = Cookie(None)) -> dict:
    with db.connect() as conn:
        if not _require_admin(conn, tos_session, response):
            return {"error": "admin only"}
        return {"pending": receipts_verification.pending(conn)}


@app.post("/api/admin/callers/{verification_id}/verify")
def admin_review_verification(verification_id: int, req: VerifyReviewReq, response: Response,
                              tos_session: str | None = Cookie(None)) -> dict:
    with db.connect() as conn:
        if not _require_admin(conn, tos_session, response):
            return {"error": "admin only"}
        out = receipts_verification.review(verification_id, req.approve, conn)
        if "error" in out:
            response.status_code = 400
        return out


@app.post("/api/calls")
def publish_call(req: CallReq, response: Response, tos_session: str | None = Cookie(None)) -> dict:
    """Seal a call. Rate limited: see _limit_bucket.

    Returns the sealed row INCLUDING its hashes, because the receipt is the product. A caller who
    publishes and is shown only "saved" has been given no more than any other form would give them.
    """
    with db.connect() as conn:
        user = authn.session_user(conn, tos_session)
        if not user:
            response.status_code = 401
            return {"error": "sign in first"}
        caller = _caller_for_user(conn, user["id"])
        if not caller:
            response.status_code = 404
            return {"error": "claim a handle before publishing."}
        try:
            call = receipts_calls.publish(caller["id"], req.model_dump(), conn)
        except receipts_calls.PublishError as exc:
            response.status_code = 400
            return {"error": "this call was not published.", "problems": exc.problems}
        return {"call": call}


@app.get("/api/calls/scoreability")
def call_scoreability(symbol: str, response: Response,
                      tos_session: str | None = Cookie(None)) -> dict:
    """Live check as a symbol is typed on the publish form. Behind a session: it is a database
    read on behalf of someone about to publish, not a public lookup."""
    with db.connect() as conn:
        if not authn.session_user(conn, tos_session):
            response.status_code = 401
            return {"error": "sign in first"}
        return receipts_calls.scoreability(symbol, conn)


@app.get("/api/calls/symbols")
def call_symbols(response: Response, q: str = "",
                 tos_session: str | None = Cookie(None)) -> dict:
    """Ticker autocomplete, restricted to symbols a call could actually be scored on.

    Behind a session for the same reason `scoreability` is: it is a read on behalf of someone about
    to publish, not a public lookup of what this database holds.
    """
    with db.connect() as conn:
        if not authn.session_user(conn, tos_session):
            response.status_code = 401
            return {"error": "sign in first"}
        return receipts_universe.suggest(conn, q)


@app.get("/api/calls/preview")
def call_preview(response: Response, symbol: str, horizon_days: int = 30,
                 tos_session: str | None = Cookie(None)) -> dict:
    """What a caller is committing to, before they commit to it. See `calls.preview`."""
    with db.connect() as conn:
        if not authn.session_user(conn, tos_session):
            response.status_code = 401
            return {"error": "sign in first"}
        if horizon_days not in receipts_calls.SCOREABLE_HORIZONS:
            response.status_code = 400
            return {"error": "the horizon has to be 7, 30 or 90 days."}
        # The panel used to print our last close for the symbol and for SPY. A caller who notices
        # they are gone is owed the reason rather than left to assume we lost the data.
        return {**receipts_calls.preview(symbol, horizon_days, conn),
                "no_prices": receipts_record.NO_PRICES}


@app.get("/api/calls/{call_id}")
def one_call(call_id: int, response: Response) -> dict:
    """One call with everything a sceptic needs to check it by hand. Public."""
    with db.connect() as conn:
        call = receipts_calls.get(call_id, conn)
        if not call:
            response.status_code = 404
            return {"error": "no such call."}
        with conn.cursor() as cur:
            cur.execute("""SELECT c.handle, c.display_name, c.kind, c.is_house, c.verified_at,
                                  k.context_snapshot
                             FROM calls k JOIN callers c ON c.id = k.caller_id
                            WHERE k.id = %s""", (call_id,))
            handle, name, kind, is_house, verified_at, snapshot = cur.fetchone()
        return {"call": call, "noise_floor": receipts_scoring.NOISE_FLOOR,
                "context_snapshot": snapshot,
                "caller": {"handle": handle, "display_name": name, "kind": kind,
                           "is_house": is_house, "verified": verified_at is not None},
                # This response carries a score, so it carries the line that tells a reader how to
                # check it without our prices. Sent from here rather than typed into the React
                # proof panel, so the page and the methodology cannot come to say different things.
                "recompute": receipts_record.RECOMPUTE_NOTE,
                "no_prices": receipts_record.NO_PRICES,
                "disclaimer": RECEIPTS_DISCLAIMER}


@app.get("/api/receipts/methodology")
def receipts_methodology() -> dict:
    """The scoring rules as structured data, so no surface ever hardcodes them and drifts."""
    with db.connect() as conn:
        return {**receipts_record.methodology(),
                "universe": receipts_record.scoreable_universe(conn),
                "disclaimer": RECEIPTS_DISCLAIMER}


def _record_payload(caller: dict, conn) -> dict:
    """One caller's whole record, assembled once.

    Shared by `/api/receipts/{handle}` and by the server-rendered public page at `/r/{handle}`, so
    the two cannot drift into showing different records for the same caller — and so the sample
    gate, which lives in `record.summary`, is applied in one place that neither surface can route
    around.
    """
    cid = caller["id"]
    # `listing` is newest first, so its first row carries the chain head. Reading the calls a
    # second time through `for_chain` would double the work of the heaviest query on this page
    # for a count and one hash. `for_chain` is still the only input to actual VERIFICATION,
    # where reading exactly the sealed fields and nothing else is the whole point.
    listing = receipts_calls.listing(cid, conn, full=False)
    out = {
        "caller": caller,
        "summary": receipts_record.summary(cid, conn),
        "misses": receipts_record.recent_misses(cid, 10, conn),
        "calibration": receipts_record.calibration(cid, conn),
        "calls": listing,
        # The open ones, split out rather than left for a surface to filter. They get their own
        # panel because Part A gave them a stored REASON (migration 036) and a blank row past
        # its horizon is indistinguishable, to a sceptic, from a result being withheld. Oldest
        # first: the one that has been waiting longest is the one a reader should see first,
        # which is the opposite of the newest-first ordering the full list wants.
        "open_calls": [c for c in reversed(listing) if c["verdict"] is None],
        "chain_links": len(listing),
        "chain_head": listing[0]["content_hash"] if listing else receipts_chain.GENESIS_HASH,
        "disclaimer": RECEIPTS_DISCLAIMER,
    }
    if caller["is_house"]:
        # Whose record is this. The pooled house figure is the one the banner quotes, and a
        # surface that showed one version's rate under a sentence about the other would be
        # repeating the exact mistake the marketing site made with the Ledger.
        out["house"] = receipts_record.house_summary(conn)
    return out


@app.get("/api/receipts/{handle}")
def receipts_for(handle: str, response: Response) -> dict:
    """One caller's whole record. Public, and misses come first."""
    with db.connect() as conn:
        caller = receipts_record.caller(handle, conn)
        if not caller:
            response.status_code = 404
            return {"error": "no such record."}
        return _record_payload(caller, conn)


@app.get("/api/receipts/{handle}/verify")
def receipts_verify(handle: str, response: Response) -> dict:
    """Recompute every hash in the caller's chain, live. Public, and the point of the product."""
    with db.connect() as conn:
        caller = receipts_record.caller(handle, conn)
        if not caller:
            response.status_code = 404
            return {"error": "no such record."}
        sealed = receipts_calls.for_chain(caller["id"], conn)
        result = receipts_chain.verify_chain(sealed)
        return {"handle": caller["handle"], **result,
                "sealed_fields": list(receipts_chain.SEALED_FIELDS),
                "caveat": receipts_record.methodology()["chain"]["does_not_prove"]}


@app.get("/api/receipts/{handle}/chain")
def receipts_chain_data(handle: str, response: Response) -> dict:
    """The sealed fields of every call, and NO verdict on them. Public.

    This is the half of verification that belongs to the reader. `/verify` above recomputes the
    chain on our server and answers `intact: true`, which is the operator of the database asking to
    be trusted — fine as an API, useless as evidence, and the public record page must not rest on
    it. So this hands over exactly what was hashed and stops, and `receipts/verify.js` does the
    SHA-256 in the visitor's own browser.

    The values are rendered by `chain.rendered_fields` rather than sent as JSON types. Two of the
    ten are timestamps whose sealed spelling includes microseconds and a trailing Z, both of which
    a JavaScript `Date` round trip drops; asking a client to reinvent that would mean an intact
    record reporting as broken. The FRAMING — the length prefixes that stop a thesis being mistaken
    for structure — is deliberately left to the client, because that is the part worth computing
    independently.
    """
    with db.connect() as conn:
        caller = receipts_record.caller(handle, conn)
        if not caller:
            response.status_code = 404
            return {"error": "no such record."}
        sealed = receipts_calls.for_chain(caller["id"], conn)
    response.headers["Cache-Control"] = "public, max-age=60"
    return {
        "handle": caller["handle"],
        "fields": list(receipts_chain.SEALED_FIELDS),
        "genesis": receipts_chain.GENESIS_HASH,
        "links": [{"seq": c["seq"], "prev_hash": c["prev_hash"],
                   "content_hash": c["content_hash"],
                   "values": receipts_chain.rendered_fields(c)} for c in sealed],
        # How the client must frame those values before hashing, stated on the wire rather than
        # only in two codebases. A third implementation — someone checking this record in a
        # language we never wrote — should not have to read our source to get the bytes right.
        "framing": ("each field as name:byte-length-of-value:value, joined with newline; "
                    "sha256 of (prev_hash + payload), hex"),
        "does_not_prove": receipts_record.methodology()["chain"]["does_not_prove"],
    }


@app.get("/api/board")
def receipts_board() -> dict:
    """Every caller with their record. Public."""
    with db.connect() as conn:
        return {"board": receipts_record.board(conn),
                "house": receipts_record.house_summary(conn),
                "sample_gate": receipts_record.SAMPLE_GATE,
                "ranking_note": ("This ranks how often past public statements turned out right, "
                                 "measured against SPY over each caller's own stated horizons. It "
                                 "is a measurement of the past. It is not investment advice, it is "
                                 "not a recommendation, and a high position is not an endorsement "
                                 "of any person or a reason to follow them."),
                "disclaimer": RECEIPTS_DISCLAIMER}


def _receipt_card_args(handle: str) -> dict | None:
    """Everything either renderer needs, read once. None if no such handle.

    Shared so the PNG and the SVG cannot drift into showing different records for the same
    caller — and in particular so the sample gate is applied once. `record.summary` refuses to
    return a rate below the gate, so neither renderer can print one that has not cleared it.
    """
    with db.connect() as conn:
        caller = receipts_record.caller(handle, conn)
        if not caller:
            return None
        summary = receipts_record.summary(caller["id"], conn)
        links = len(receipts_calls.for_chain(caller["id"], conn))
    return {"handle": caller["handle"], "display_name": caller["display_name"],
            "counts": summary["counts"], "hit_rate": summary["hit_rate"],
            "hit_rate_ci": summary["hit_rate_ci"],
            "resolved_scoreable": summary["resolved_scoreable"], "links": links,
            "brand": config.brand_name(), "verified": caller["verified_at"] is not None,
            "is_house": caller["is_house"]}


@app.get("/api/card/receipt/{handle}.png")
def receipt_card_png(handle: str) -> Response:
    """THE share card: what a link preview actually renders.

    PNG rather than SVG because no major platform renders SVG as a preview image — X's card spec
    accepts JPG, PNG, WEBP and GIF, and Facebook's scraper does not accept SVG either. The SVG
    below is kept for the page body, where a browser renders it sharper at any size.
    """
    args = _receipt_card_args(handle)
    if not args:
        # A 1x1 rather than an empty body: a scraper that follows og:image for a deleted handle
        # should get a valid image it can discard, not a decode error.
        return Response(content=receipts_card.receipt_card_png(
            handle=handle, display_name="No record here", counts={}, hit_rate=None,
            hit_rate_ci=None, resolved_scoreable=0, links=0, brand=config.brand_name()),
            media_type="image/png", status_code=404)
    return Response(content=receipts_card.receipt_card_png(**args), media_type="image/png",
                    headers={"Cache-Control": "public, max-age=300"})


@app.get("/api/card/receipt/{handle}.svg")
def receipt_card(handle: str) -> Response:
    """The same card as SVG, for the page body. Public, and it may never print a rate on a gated
    record.

    Served from `receipts.card` rather than `presentation`, which is not tidying: `presentation`
    opens with `from .signals.convergence import DEFAULT_PARAMS`, so this route imported the dead
    convergence plane. `docs/receipts_gap_analysis.md` §5.3 found it by measurement after
    `docs/receipts_protected.md` had recorded `signals/` as not a dependency -- the dependency ran
    through the ROUTE, which a package graph rooted at `receipts/` cannot see.
    """
    args = _receipt_card_args(handle)
    if not args:
        return Response(content="<svg xmlns='http://www.w3.org/2000/svg'/>",
                        media_type="image/svg+xml", status_code=404)
    return Response(content=receipts_card.receipt_card_svg(**args), media_type="image/svg+xml",
                    headers={"Cache-Control": "public, max-age=300"})


# The verifier the public record page runs, served as a FILE.
#
# `script-src 'self'` means an inline script is refused by the browser, silently and with nothing
# in our logs — so the flagship interaction of the product would be dead on the page with no
# symptom anywhere. Registered before the SPA mount, which is a catch-all.
_VERIFY_JS_PATH = Path(__file__).parent / "receipts" / "verify.js"
_verify_js_cache: tuple[float, str] | None = None


def _verify_js() -> str:
    """The verifier's source, cached against its own mtime.

    Cached rather than read fresh because this is on the public path; keyed on mtime rather than
    read once at import because of a trap that cost real time. Under `make dev` uvicorn's
    `--reload` watches only `*.py` — and `--reload-include '*.js'` does NOT fix it, because that
    flag needs `watchfiles`, which is not in `requirements.txt`; uvicorn falls back to `StatReload`
    and logs "--reload-include and --reload-exclude have no effect unless watchfiles is installed".
    So an import-time read served the OLD bytes behind a clean 200 while the file on disk moved,
    and edits to the flagship interaction appeared to do nothing.

    One `stat()` per request, on a route the browser caches for five minutes and hits once per page
    load, is the honest price for never debugging that again. It also costs production nothing: the
    file never changes between deploys, so the read happens once per process.
    """
    global _verify_js_cache
    mtime = _VERIFY_JS_PATH.stat().st_mtime
    if _verify_js_cache is None or _verify_js_cache[0] != mtime:
        _verify_js_cache = (mtime, _VERIFY_JS_PATH.read_text())
    return _verify_js_cache[1]


@app.get("/receipt-verify.js", include_in_schema=False)
def receipt_verify_js() -> Response:
    return Response(content=_verify_js(), media_type="text/javascript; charset=utf-8",
                    headers={"Cache-Control": "public, max-age=300"})


@app.get("/r/{handle}", response_class=HTMLResponse)
def receipt_share_page(handle: str, response: Response) -> str:
    """THE public record. Server rendered, signed out, and stripped of everything that is not the
    record.

    This is where every shared link lands. It used to be a card image and a link into the app,
    which meant a stranger clicked twice to see anything they could judge and arrived inside a
    research terminal with eleven nav items that 401 for them. See `receipts/page.py` for why it is
    rendered here rather than by the bundle.
    """
    brand = config.brand_name()
    with db.connect() as conn:
        caller = receipts_record.caller(handle, conn)
        data = _record_payload(caller, conn) if caller else None

    if not data:
        # 404 WITH a readable page, not one or the other. The rule this page has always followed is
        # that a dead handle gets a page a person can read rather than a stack trace \u2014 but it was
        # doing that with a 200, which tells a crawler the mistyped link is a real record and
        # leaves a link checker unable to tell a dead handle from a live one. `/api/receipts/
        # {handle}` already 404s for the same input, so the two surfaces disagreed about the same
        # fact. The status is for machines and the body is for people; they are not in tension.
        response.status_code = 404
        body = receipts_page.not_found(handle, brand)
        return _receipt_document(title=f"No such record \u00b7 {brand}", tags="", body=body)

    caller = data["caller"]
    summary, counts = data["summary"], data["summary"]["counts"]
    if summary["gated"]:
        line = (f'{counts["hit"]} hit, {counts["miss"]} miss, {counts["inconclusive"]} '
                f'inconclusive. A rate is not shown below {receipts_record.SAMPLE_GATE} resolved '
                f'calls.')
    else:
        line = (f'{summary["hit_rate"]:.1%} right on {summary["resolved_scoreable"]} resolved '
                f'calls, measured against SPY.')

    title = f'{caller["display_name"]} \u00b7 the record \u00b7 {brand}'
    # PNG in the tags, because no major platform renders an SVG as a link preview.
    tags = _og_tags(title=title, description=line, path=f"/r/{caller['handle']}",
                    image_path=f"/api/card/receipt/{caller['handle']}.png")
    methodology = receipts_record.methodology()
    return _receipt_document(
        title=title, tags=tags,
        body=receipts_page.render(data, brand=brand, methodology=methodology,
                                  caveat=methodology["chain"]["does_not_prove"]))


def _receipt_document(title: str, tags: str, body: str) -> str:
    """The HTML frame. The stylesheet is inline and the only script is the verifier.

    `receipts.card._xml_escape` rather than a helper from `presentation`: that module opens with
    `from .signals.convergence import DEFAULT_PARAMS`, so borrowing one line from it would hold the
    dead convergence plane open from the public record page.
    """
    e = receipts_card._xml_escape
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<title>{e(title)}</title>{tags}'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<style>{receipts_page.STYLE}</style>'
            f'<script type="module" src="/receipt-verify.js" defer></script>'
            f'</head><body>{body}</body></html>')


# ------------------------------------------------------------------- frontend (SPA)
#
# THE MARKETING SITE IS GONE AND "/" IS THE BOARD. `site/` was a 44 MB sibling Vite project that
# pitched the research terminal, and a signed-out stranger arriving at "/" was redirected into it
# on the presence of a session cookie. Deleting it without repointing "/" would have left a
# stranger on a 404, and repointing it anywhere but the Board would have been worse than that: the
# Board IS the pitch now. It is the only surface guaranteed to have something on it from a cold
# start, because our own record is always on it — 473 sealed calls, 43.2% right, below a coin flip,
# which is a more honest introduction than any landing page could be.
#
# So "/" falls through to the SPA mount below like every other path, the redirect and its
# cookie-sniffing are deleted, and signing out sends the reader to "/" rather than to "/site/".

_STATIC_DIR = Path(__file__).parent / "static"

if (_STATIC_DIR / "index.html").exists():
    class _SpaFiles(StaticFiles):
        """Serve the built bundle, and hand any unmatched path back to index.html so client routes
        survive a refresh, a bookmark, or a shared link. API routes are registered above this mount
        and are matched first, so they are unaffected.

        StaticFiles signals a miss by RAISING HTTPException(404), not by returning one, so the
        fallback has to catch rather than inspect a status code."""

        async def get_response(self, path: str, scope):
            try:
                return await super().get_response(path, scope)
            except StarletteHTTPException as exc:
                # Only a plain miss falls back; a bad method or a path with a real asset extension
                # should still 404 rather than silently returning HTML.
                if exc.status_code != 404 or path.startswith("api/") or "." in path.rsplit("/", 1)[-1]:
                    raise
                return await super().get_response("index.html", scope)

    app.mount("/", _SpaFiles(directory=str(_STATIC_DIR), html=True), name="spa")
else:
    @app.get("/", response_class=HTMLResponse)
    def _no_build() -> str:
        return (f"<h1>{config.brand_name()} API</h1><p>The dashboard bundle is not built. Run the multi-stage "
                "Docker build, or <code>cd frontend && npm install && npm run build</code>. "
                "API is live at <code>/api/clusters</code>, <code>/api/feeds</code>, "
                "<code>/api/definitions</code>.</p>")
