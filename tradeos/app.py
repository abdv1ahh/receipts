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
import time
from datetime import UTC, date, datetime, timedelta
from io import BytesIO
from pathlib import Path

from fastapi import BackgroundTasks, Cookie, FastAPI, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from psycopg import sql
from psycopg.types.json import Json
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import (
    admin,
    apikeys,
    assistant,
    authn,
    billing,
    community,
    config,
    crypto,
    crypto_intel,
    db,
    exposure,
    flags,
    geography,
    insights,
    journal_context,
    ledger,
    mail,
    oauth,
    onboarding,
    portfolio,
    presentation,
    public_site,
    ratelimit,
    relevance,
    search,
    sentiment,
    sources,
    trades,
    watchlist_accounts,
)
from . import brief as brief_mod
from . import dashboard as dashboard_mod
from . import events as events_mod
from . import news as news_mod
from . import (
    radar as radar_mod,
)
from . import scheduler as scheduler_mod
from . import social as social_mod
from .receipts import calls as receipts_calls
from .receipts import card as receipts_card
from .receipts import chain as receipts_chain
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


class FollowReq(BaseModel):
    kind: str
    ref: str
    label: str | None = None


class AlertPrefsReq(BaseModel):
    new_high_conviction: bool
    followed_activity: bool
    min_score: int
    email_enabled: bool


class PortfolioReq(BaseModel):
    name: str
    kind: str = "manual"
    buckets: list[str] | None = None


class PositionReq(BaseModel):
    symbol: str
    opened_on: str | None = None


class CheckoutReq(BaseModel):
    plan: str


class ApiKeyReq(BaseModel):
    name: str | None = None


class TradeReq(BaseModel):
    symbol: str | None = None
    asset_class: str = "equity"
    direction: str = "long"
    status: str = "planned"
    entry_price: float | None = None
    exit_price: float | None = None
    stop_price: float | None = None
    target_price: float | None = None
    size: float | None = None
    size_unit: str = "shares"
    timeframe: str | None = None
    strategy: str | None = None
    reason_entry: str | None = None
    reason_exit: str | None = None
    confidence: int | None = None
    expected_outcome: str | None = None
    opened_on: str | None = None
    closed_on: str | None = None
    is_public: bool = False


class AssistantReq(BaseModel):
    message: str


class SimulateReq(BaseModel):
    symbol: str | None = None
    direction: str = "long"
    entry_price: float | None = None
    stop_price: float | None = None
    target_price: float | None = None
    size: float | None = None
    size_unit: str = "shares"
    account_size: float | None = None


class ProfileReq(BaseModel):
    handle: str | None = None
    bio: str | None = None


class FollowUserReq(BaseModel):
    handle: str


class CommentReq(BaseModel):
    body: str


class ReactReq(BaseModel):
    kind: str


class ReportReq(BaseModel):
    target_type: str
    target_id: int
    reason: str | None = None


class AdminResolveReq(BaseModel):
    target_type: str
    target_id: int
    action: str          # hide | unhide | dismiss


class AdminTierReq(BaseModel):
    tier: str            # free | retail | pro


class AdminBanReq(BaseModel):
    banned: bool


class AdminFlagReq(BaseModel):
    enabled: bool


class ProfileFrameReq(BaseModel):
    """The reader's geographic and monetary frame — what makes relevance personal."""
    country: str | None = None
    base_currency: str | None = None
    sectors: list[str] = []
    risk_appetite: str | None = None


class EmailReq(BaseModel):
    email: str


class TokenReq(BaseModel):
    token: str


class ResetConfirmReq(BaseModel):
    token: str
    password: str


class RadarFilterReq(BaseModel):
    """A saved filter set. `spec` is normalised into a fixed shape before storage — see
    radar.normalise_spec; nothing arbitrary is ever persisted or matched against."""
    name: str
    spec: dict = {}
    subscribed: bool = False
    channel: str | None = None
    webhook_url: str | None = None
    throttle_mins: int = 360


class OnboardingReq(BaseModel):
    """Everything the sixty-second setup collects. Every field optional — finishing with nothing
    chosen is a valid answer, and the flow records that it was asked rather than asking again."""
    country: str | None = None
    base_currency: str | None = None
    symbols: list[str] = []


class WatchlistAccountReq(BaseModel):
    """One consequential account. `influence` is validated in watchlist_accounts.upsert so the
    range rule lives with the data, not scattered across callers."""
    platform: str
    handle: str
    display_name: str
    role: str | None = None
    domain: str | None = None
    country: str | None = None
    influence: float = 0.5
    feed_url: str | None = None
    active: bool = True
    note: str | None = None


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


def _rate_ok(limit: int = 20, window: int = 60) -> bool:
    now = time.time()
    _extract_calls[:] = [t for t in _extract_calls if now - t < window]
    if len(_extract_calls) >= limit:
        return False
    _extract_calls.append(now)
    return True


# ---- user-uploaded trade screenshots: re-encoded, opaque-named, served through an authed route
UPLOADS_DIR = Path(os.environ.get("UPLOADS_DIR", str(Path(__file__).parent.parent / "uploads")))
_IMG_KEY = re.compile(r"[0-9a-f]{32}\.png")


def _image_path(key: str | None) -> Path | None:
    return UPLOADS_DIR / key if key and _IMG_KEY.fullmatch(key) else None


# A chart screenshot is a PNG, a JPEG, a WebP or a GIF. Nothing else needs to be decodable.
#
# Pillow ships decoders for PSD, FITS, PCF, BDF and a long tail of others, and several of those
# have a history of memory-safety bugs — the version this repo pinned until Phase 9 had a
# known out-of-bounds write and a memory-corruption issue, both reachable by uploading a crafted
# PSD, because `Image.open` sniffs the format from the bytes and the caller never said which
# formats it wanted. Upgrading fixes the known ones; refusing to decode formats the product has no
# use for is what keeps the next one out of reach.
_ALLOWED_IMAGE_FORMATS = {"PNG", "JPEG", "WEBP", "GIF"}


def _store_image(body: bytes) -> str:
    """Re-encode an upload to a normalized PNG under an opaque key: strips EXIF/metadata and
    neutralizes any non-image payload (polyglots); a pixel cap bounds decompression bombs."""
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = 40_000_000

    # Order matters. `Image.open` reads only the header, so the format can be checked BEFORE
    # anything calls a decoder — `verify()` and `convert()` below both decode. Checking afterwards
    # would mean the vulnerable path had already run.
    probe = Image.open(BytesIO(body))
    if probe.format not in _ALLOWED_IMAGE_FORMATS:
        raise ValueError(f"unsupported image format: {probe.format}")

    Image.open(BytesIO(body)).verify()             # reject truncated / lying files
    im = Image.open(BytesIO(body)).convert("RGB")  # re-open (verify consumed it); drop alpha/EXIF
    im.thumbnail((2000, 2000))
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    key = secrets.token_hex(16) + ".png"
    im.save(UPLOADS_DIR / key, format="PNG")
    return key


def _delete_image(key: str | None) -> None:
    p = _image_path(key)
    try:
        if p and p.exists():
            p.unlink()
    except OSError:
        pass


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


@app.get("/api/onboarding")
def activation_checklist(tos_session: str | None = Cookie(None)) -> dict:
    """Per-user activation progress, so a new account gets a short 'get value fast' checklist.

    Named for what it is rather than for its path: as a plain `onboarding` it shadowed the module
    of the same name the moment Phase 8 imported one, and every call to `onboarding.state` became
    an AttributeError on a function. The route is unchanged."""
    with db.connect() as conn, conn.cursor() as cur:
        user = authn.session_user(conn, tos_session)
        if not user:
            return {"authenticated": False}
        uid = user["id"]
        cur.execute("SELECT count(*) FROM follows WHERE user_id=%s", (uid,))
        follows = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM portfolios WHERE user_id=%s", (uid,))
        portfolios = cur.fetchone()[0]
        cur.execute("SELECT 1 FROM alert_prefs WHERE user_id=%s", (uid,))
        has_prefs = cur.fetchone() is not None
        cur.execute("SELECT count(*) FROM notifications WHERE user_id=%s", (uid,))
        notifs = cur.fetchone()[0]
    alerts_on = has_prefs or notifs > 0
    return {"authenticated": True, "follows": follows, "portfolios": portfolios,
            "alerts_configured": alerts_on, "complete": follows > 0 and portfolios > 0 and alerts_on}


# ------------------------------------------------------------- first-run onboarding (Phase 8)
#
# Separate from `/api/onboarding` above, which is the older activation checklist (follows,
# portfolios, alerts). This one fills the reader's FRAME, without which relevance cannot rank.

@app.get("/api/profile/onboarding")
def profile_onboarding(tos_session: str | None = Cookie(None)) -> dict:
    """Whether this reader still needs asking, plus the countries that can be chosen."""
    with db.connect() as conn:
        user = authn.session_user(conn, tos_session)
        if not user:
            return {"authenticated": False}
        return {"authenticated": True, **onboarding.state(conn, user["id"]),
                "countries": onboarding.countries(conn)}


@app.post("/api/profile/onboarding")
def profile_onboarding_save(req: OnboardingReq, response: Response,
                            tos_session: str | None = Cookie(None)) -> dict:
    with db.connect() as conn:
        user = authn.session_user(conn, tos_session)
        if not user:
            response.status_code = 401
            return {"error": "log in first"}
        out = onboarding.complete(conn, user["id"], req.country, req.base_currency, req.symbols)
        if out.get("error"):
            response.status_code = 400
        return out


@app.post("/api/profile/onboarding/skip")
def profile_onboarding_skip(response: Response, tos_session: str | None = Cookie(None)) -> dict:
    """Dismiss for a few days. Never permanently — see the note in `onboarding.snooze`."""
    with db.connect() as conn:
        user = authn.session_user(conn, tos_session)
        if not user:
            response.status_code = 401
            return {"error": "log in first"}
        return onboarding.snooze(conn, user["id"])


@app.get("/api/referral")
def referral(tos_session: str | None = Cookie(None)) -> dict:
    """A user's reusable referral code + how many people have joined through it. Sharing the code as
    an invite opens signup, and a referred user gets a 14-day Pro trial (authn._grant_trial)."""
    with db.connect() as conn:
        user = authn.session_user(conn, tos_session)
        if not user:
            return {"authenticated": False}
        return {"authenticated": True, **authn.referral_stats(conn, user["id"])}


def _tier_of(conn, token: str | None) -> str:
    return (authn.session_user(conn, token) or {}).get("tier", "free")


def _effective_as_of(cur, requested: str, tier: str):
    """The freshest cluster set this tier may see. Free/unauthenticated get a 48h delay; the
    cutoff is applied server-side, so no as_of/id/param can reach fresher data (decision #36)."""
    d = authn.delay_hours(tier)
    if requested == "latest":
        cur.execute("SELECT max(as_of) FROM signal_clusters WHERE as_of <= now() - make_interval(hours => %s)", (d,))
    else:
        cur.execute("SELECT max(as_of) FROM signal_clusters WHERE as_of <= LEAST(%s, now() - make_interval(hours => %s))",
                    (datetime.fromisoformat(requested), d))
    return cur.fetchone()[0]


# ------------------------------------------------------------------ honesty surface

@app.get("/api/feeds")
def feeds() -> dict:
    with db.connect() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT source, last_success_at, last_record_knowable, records_total, rejects_total
               FROM feed_health ORDER BY source"""
        )
        rows = [
            {
                "source": r[0],
                "last_success_at": r[1].isoformat() if r[1] else None,
                "freshest_record_knowable": r[2].isoformat() if r[2] else None,
                "records_total": r[3],
                "rejects_total": r[4],
            }
            for r in cur.fetchall()
        ]
        cur.execute("SELECT count(*) FROM insider_transactions")
        insiders = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM stake_events")
        stakes = cur.fetchone()[0]
        cur.execute("SELECT count(*), count(*) FILTER (WHERE issuer_entity IS NULL) FROM fund_holdings")
        holdings_total, holdings_unresolved = cur.fetchone()
    return {
        "feeds": rows,
        "counts": {"insider_transactions": insiders, "stake_events": stakes, "fund_holdings": holdings_total},
        "unresolved": {"fund_holdings": holdings_unresolved},
    }


@app.get("/api/ledger")
def ledger_view() -> dict:
    """The system's own accuracy record, including its misses.

    Public and read-only by design: this is the number that has to be believable, and a record
    only visible to its author is worth nothing. Nothing here is user-scoped."""
    with db.connect() as conn:
        return {"ledger": ledger.summary(conn), "recent_misses": ledger.recent_misses(conn, limit=10),
                "brand": config.brand_name()}


# ------------------------------------------------------------------- the marketing site (Phase 7)
#
# Everything under /api/public is served to anonymous callers by design. It takes no session and
# reads nothing user-scoped — see the module docstring in `public_site.py` for the boundary.

@app.get("/api/public/walkthrough")
def public_walkthrough() -> dict:
    """One real interpretation walked end to end, rotating daily over the live store."""
    with db.connect() as conn:
        return public_site.walkthrough(conn)


@app.get("/api/public/frame")
def public_frame(country: str | None = None, limit: int = 5) -> dict:
    """The same day read from one country — the personalisation demo, without an account."""
    with db.connect() as conn:
        return public_site.frame_preview(conn, country, limit)


@app.get("/api/public/live")
def public_live(limit: int = 5) -> dict:
    """The freshest event-derived interpretations, for the hero. No ranking, no reader."""
    with db.connect() as conn:
        return {"claims": public_site.live_claims(conn, limit), "brand": config.brand_name()}


# ------------------------------------------------------------------- saved filters (Phase 4)

@app.get("/api/radar/filters")
def radar_filters(tos_session: str | None = Cookie(None)) -> dict:
    with db.connect() as conn:
        user = authn.session_user(conn, tos_session)
        if not user:
            return {"authenticated": False, "filters": []}
        return {"authenticated": True, "filters": radar_mod.listing(conn, user["id"]),
                "min_throttle_mins": radar_mod.MIN_THROTTLE_MINS,
                "max_filters": radar_mod.MAX_FILTERS}


@app.post("/api/radar/filters")
def radar_filter_save(req: RadarFilterReq, response: Response,
                      tos_session: str | None = Cookie(None)) -> dict:
    with db.connect() as conn:
        user = authn.session_user(conn, tos_session)
        if not user:
            response.status_code = 401
            return {"error": "log in to save a filter"}
        out = radar_mod.save(conn, user["id"], req.name, req.spec, req.subscribed,
                             req.channel, req.webhook_url, req.throttle_mins)
        if out.get("error"):
            response.status_code = 400
        return out


@app.delete("/api/radar/filters/{fid}")
def radar_filter_delete(fid: int, response: Response,
                        tos_session: str | None = Cookie(None)) -> dict:
    with db.connect() as conn:
        user = authn.session_user(conn, tos_session)
        if not user:
            response.status_code = 401
            return {"error": "not authenticated"}
        return radar_mod.delete(conn, user["id"], fid)


@app.post("/api/radar/filters/preview")
def radar_filter_preview(req: RadarFilterReq, tos_session: str | None = Cookie(None)) -> dict:
    """How many recent claims this spec would have caught — so a filter that matches nothing is
    visible while editing rather than after a week of silence."""
    with db.connect() as conn:
        if not authn.session_user(conn, tos_session):
            return {"authenticated": False}
        return {"authenticated": True, **radar_mod.preview(conn, req.spec)}


@app.get("/api/claims")
def claims_list(hours: int = 72, limit: int = 40, tos_session: str | None = Cookie(None)) -> dict:
    """Live interpretations, ranked by relevance to the reader when they have a profile.

    Relevance is computed here rather than in the client so the ranking cannot be gamed, and each
    item carries WHY it ranked where it did — an unexplained order is indistinguishable from an
    arbitrary one."""
    hours, limit = max(1, min(720, hours)), max(1, min(100, limit))
    with db.connect() as conn, conn.cursor() as cur:
        user = authn.session_user(conn, tos_session)
        profile, exposure, watchlist = relevance.reader_frame(cur, (user or {}).get("id"))
        cur.execute(
            """SELECT c.id, c.created_at, c.mechanism, c.affected, c.horizon, c.confidence,
                      c.analogs, c.reasoning_trace, c.contradicts, c.status, c.model_version,
                      e.title, e.source, e.source_url, e.geo, e.category,
                      cl.novelty_score, cl.source_count, c.cluster_id, c.supersedes,
                      -- The most consequential voice that carried this story. A cluster gathers
                      -- many reports; what matters for ranking is whether a central bank said it
                      -- or an aggregator repeated it, so this is the MAX across the cluster and
                      -- NULL when nothing in it has a named author (which is most of them).
                      (SELECT max(ev.author_influence) FROM events ev
                        WHERE ev.cluster_id = c.cluster_id)
                 FROM claims c
                 LEFT JOIN events e ON e.id = c.event_id
                 LEFT JOIN event_clusters cl ON cl.id = c.cluster_id
                WHERE c.created_at >= now() - make_interval(hours => %s)
             ORDER BY c.created_at DESC LIMIT %s""", (hours, limit))
        cols = ("id", "created_at", "mechanism", "affected", "horizon", "confidence", "analogs",
                "reasoning_trace", "contradicts", "status", "model_version", "headline", "source",
                "url", "geo", "category", "novelty", "source_count", "cluster_id", "supersedes",
                "author_influence")
        rows = [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

    out = []
    for r in rows:
        scored = relevance.score(r, profile, exposure, watchlist, r.get("novelty"))
        r["created_at"] = r["created_at"].isoformat()
        out.append({**r, **scored, "why_shown": relevance.explain(scored["parts"])})
    out.sort(key=lambda x: x["relevance"], reverse=True)
    # Threading (Phase 4): claims on one cluster are one developing story, newest reading first
    # with its history attached, rather than twelve near-duplicate cards.
    out = radar_mod.thread(out)
    return {"claims": out, "personalised": bool(profile and profile.get("country")),
            "profile": profile,
            "disclaimer": "Informational analysis of public information, not personalised "
                          "investment advice. Every interpretation carries its confidence and is "
                          "scored in the Ledger once its horizon elapses."}


@app.put("/api/profile/frame")
def profile_frame_set(req: ProfileFrameReq, response: Response,
                      tos_session: str | None = Cookie(None)) -> dict:
    """Set the reader's country and currency. Relevance scoring is worthless without it, which is
    why onboarding (Phase 8) exists mainly to fill this in."""
    with db.connect() as conn, conn.cursor() as cur:
        user = authn.session_user(conn, tos_session)
        if not user:
            response.status_code = 401
            return {"error": "log in to set your frame"}
        if req.country:
            cur.execute("SELECT 1 FROM country_exposure WHERE country = %s", (req.country.upper(),))
            if not cur.fetchone():
                response.status_code = 400
                return {"error": f"no exposure data for {req.country} yet"}
        cur.execute(
            """INSERT INTO user_profiles (user_id, country, base_currency, sectors, risk_appetite)
               VALUES (%s,%s,%s,%s,%s)
               ON CONFLICT (user_id) DO UPDATE SET country=EXCLUDED.country,
                   base_currency=EXCLUDED.base_currency, sectors=EXCLUDED.sectors,
                   risk_appetite=EXCLUDED.risk_appetite, updated_at=now()""",
            (user["id"], (req.country or "").upper() or None, req.base_currency,
             req.sectors or [], req.risk_appetite))
        conn.commit()
    return {"saved": True}


@app.get("/api/exposure")
def exposure_view(tos_session: str | None = Cookie(None)) -> dict:
    """What your holdings are actually exposed to — the surface that replaces the position tracker.

    A broker shows what you own and what it is worth, better and with real prices. What no broker
    shows is which live events reach you, through which holding, and by what mechanism."""
    with db.connect() as conn, conn.cursor() as cur:
        user = authn.session_user(conn, tos_session)
        if not user:
            return {"authenticated": False}
        # Tier gate, enforced here rather than in the client (Phase 8, brief §14). The response
        # says plainly what the surface would show and what unlocks it — a locked feature that
        # does not explain itself is indistinguishable from a broken one.
        if not billing.entitlements(user["tier"])["exposure"]:
            return {"authenticated": True, "locked": True, "tier": user["tier"],
                    "what": "Exposure maps live interpretations onto what you hold — which event "
                            "reaches which holding, through what mechanism.",
                    "upgrade": True}
        profile, _exp, watchlist = relevance.reader_frame(cur, user["id"])

        # Holdings = the watchlist plus anything held in a portfolio. Both are things the reader
        # told us they care about; neither is a claim about what they actually own.
        cur.execute("""SELECT DISTINCT p.symbol FROM portfolio_positions p
                        JOIN portfolios pf ON pf.id = p.portfolio_id
                       WHERE pf.user_id = %s AND p.symbol IS NOT NULL""", (user["id"],))
        holdings = sorted(watchlist | {r[0].upper() for r in cur.fetchall()})
        if not holdings:
            return {"authenticated": True, "holdings": [], "empty": True}

        cur.execute("""SELECT c.id, c.mechanism, c.affected, c.confidence, c.horizon,
                              c.contradicts, e.title, e.source_url, e.category
                         FROM claims c LEFT JOIN events e ON e.id = c.event_id
                        WHERE c.created_at >= now() - interval '21 days'""")
        ccols = ("id", "mechanism", "affected", "confidence", "horizon", "contradicts",
                 "headline", "url", "category")
        claims_rows = [dict(zip(ccols, r, strict=True)) for r in cur.fetchall()]

        cur.execute("""SELECT country, name, currency, export_partners, import_partners
                         FROM country_exposure""")
        ecols = ("country", "name", "currency", "export_partners", "import_partners")
        exposure_rows = [dict(zip(ecols, r, strict=True)) for r in cur.fetchall()]

        upcoming = events_mod.upcoming(conn, days=21)

    held = set(holdings)
    touching = exposure.claims_touching(claims_rows, held)
    reach = exposure.geographic_reach(claims_rows, held)
    corridors = geography.corridors(exposure_rows)
    home = (profile or {}).get("country")
    names = {e["country"]: e["name"] for e in exposure_rows}

    return {
        "authenticated": True,
        "holdings": holdings,
        "home": home,
        "summary": exposure.summarise(holdings, touching, reach,
                                      exposure.upcoming_intersections(upcoming, held)),
        "claims": touching[:20],
        "reach": [{**r, "name": names.get(r["country"], r["country"])} for r in reach],
        "corridors": exposure.corridor_dependence(reach, corridors, home),
        "upcoming": exposure.upcoming_intersections(upcoming, held)[:10],
        "concentration": exposure.concentration([c["category"] for c in touching if c.get("category")]),
        "note": ("Exposure describes connections that already exist between what you watch and "
                 "what is happening. It is not advice, and it does not grade your choices."),
    }


@app.get("/api/globe")
def globe() -> dict:
    """What the map draws: countries lit by the events actually placed there, and the trade
    corridors between the countries we hold sourced exposure data for.

    Geography comes from what claims say they AFFECT, not from who published them — GDELT reports
    the country of the outlet, and a US wire filing about Asian exporters is not a US event."""
    with db.connect() as conn, conn.cursor() as cur:
        cur.execute("""SELECT c.id, c.affected, c.confidence, c.mechanism, c.horizon,
                              e.geo, e.category, cl.novelty_score
                         FROM claims c
                         LEFT JOIN events e ON e.id = c.event_id
                         LEFT JOIN event_clusters cl ON cl.id = c.cluster_id
                        WHERE c.created_at >= now() - interval '14 days'""")
        cols = ("id", "affected", "confidence", "mechanism", "horizon", "geo", "category", "novelty")
        claims_rows = [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

        cur.execute("""SELECT country, name, currency, currency_regime, pegged_to, main_index,
                              export_partners, import_partners, key_exports, key_imports
                         FROM country_exposure ORDER BY country""")
        ecols = ("country", "name", "currency", "currency_regime", "pegged_to", "main_index",
                 "export_partners", "import_partners", "key_exports", "key_imports")
        exposure = [dict(zip(ecols, r, strict=True)) for r in cur.fetchall()]

    # Place every claim, preferring what it AFFECTS over where it was filed.
    counts: dict[str, int] = {}
    per_country: dict[str, list[dict]] = {}
    for c in claims_rows:
        placed = geography.countries_for(c["affected"]) or list(c.get("geo") or [])
        for iso in placed:
            counts[iso] = counts.get(iso, 0) + 1
            per_country.setdefault(iso, []).append(
                {"claim_id": c["id"], "mechanism": c["mechanism"][:240],
                 "confidence": c["confidence"], "horizon": c["horizon"], "category": c["category"]})

    by_iso = {e["country"]: e for e in exposure}
    countries = [{
        "country": iso, "name": (by_iso.get(iso) or {}).get("name", iso),
        "events": n, "has_exposure_data": iso in by_iso,
        "claims": per_country.get(iso, [])[:5],
    } for iso, n in sorted(counts.items(), key=lambda kv: -kv[1])]

    return {
        "countries": countries,
        "corridors": geography.corridors(exposure),
        "exposure": {e["country"]: e for e in exposure},
        "coverage": geography.coverage(counts, len(exposure)),
    }


@app.get("/api/countries")
def countries() -> dict:
    """Which countries the product can currently personalise for. Small and honest — an unlisted
    country gets a global frame rather than a guessed one."""
    with db.connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT country, name, currency, main_index FROM country_exposure ORDER BY name")
        return {"countries": [{"country": c, "name": n, "currency": cu, "main_index": mi}
                              for c, n, cu, mi in cur.fetchall()]}


@app.get("/api/integrations")
def integrations(tos_session: str | None = Cookie(None)) -> dict:
    """Every external source in one place: connected or not, what it powers, where its free key comes
    from, when it last succeeded, and the last error if any. The owner should never again have to
    guess why a panel is empty.

    Authenticated. Raw operator detail — the last error text and per-feed row counts — goes only to
    admins: `last_error` is `str(exc)` from an arbitrary ingestion failure, and an httpx error
    embeds the full request URL. Everyone else sees that a run failed, without its text."""
    with db.connect() as conn:
        user = authn.session_user(conn, tos_session)
        if not user:
            return {"authenticated": False}
        rows = sources.health(conn, detailed=user.get("tier") == "admin")
    counts = {s: sum(1 for r in rows if r["state"] == s)
              for s in (sources.CONNECTED, sources.NEEDS_KEY, sources.UNAVAILABLE)}
    return {"authenticated": True, "sources": rows, "counts": counts, "brand": config.brand_name()}


# ------------------------------------------------------------------- merged activity

def _resolve_symbol(cur, symbol: str):
    cur.execute(
        """SELECT e.id, e.cik, e.name FROM security_map m JOIN entities e ON e.id = m.entity_id
           WHERE m.symbol = %s ORDER BY m.confidence DESC LIMIT 1""",
        (symbol.strip().upper(),),
    )
    return cur.fetchone()


def _symbol_for(cur, entity_id: int) -> str | None:
    cur.execute(
        "SELECT symbol FROM security_map WHERE entity_id = %s AND source = 'sec_company_tickers' ORDER BY confidence DESC LIMIT 1",
        (entity_id,),
    )
    r = cur.fetchone()
    return r[0] if r else None


def _staleness(event_time, knowable_time) -> dict:
    now = datetime.now(UTC)
    return {
        "event_time": event_time.isoformat(),
        "knowable_time": knowable_time.isoformat(),
        "staleness_days": (now.date() - event_time).days,
        "knowable_lag_days": (knowable_time.date() - event_time).days,
    }


def _voice_names(cur, contribution_lists: list[list[dict]]) -> dict[str, str]:
    """Batch-resolve the display name behind every voice key across a set of clusters, in two
    queries. Voice keys are 'insider:<cik>' (owner name) or 'filer:<entity_id>' (institution
    name). Names come straight from the filings — nothing invented."""
    ciks: set[str] = set()
    filer_ids: set[int] = set()
    for contribs in contribution_lists:
        for c in contribs or []:
            kind, _, ident = (c.get("voice") or "").partition(":")
            if kind == "insider" and ident:
                ciks.add(ident)
            elif kind == "filer" and ident.isdigit():
                filer_ids.add(int(ident))
    names: dict[str, str] = {}
    if ciks:
        cur.execute(
            "SELECT DISTINCT ON (owner_cik) owner_cik, owner_name FROM insider_transactions "
            "WHERE owner_cik = ANY(%s) AND owner_name IS NOT NULL ORDER BY owner_cik, knowable_time DESC",
            (list(ciks),),
        )
        for cik, nm in cur.fetchall():
            names[f"insider:{cik}"] = nm
    if filer_ids:
        cur.execute("SELECT id, name FROM entities WHERE id = ANY(%s)", (list(filer_ids),))
        for fid, nm in cur.fetchall():
            names[f"filer:{fid}"] = nm
    return names


@app.get("/api/activity")
def activity(symbol: str, limit: int = 200) -> dict:
    with db.connect() as conn, conn.cursor() as cur:
        ent = _resolve_symbol(cur, symbol)
        if ent is None:
            return {"symbol": symbol.upper(), "resolved": False, "activity": []}
        eid, cik, name = ent
        items: list[dict] = []
        cur.execute(
            """SELECT owner_name, owner_cik, transaction_code, acquired_disposed, shares, price_per_share, event_time, knowable_time
               FROM insider_transactions WHERE issuer_entity = %s ORDER BY knowable_time DESC LIMIT %s""",
            (eid, limit),
        )
        for owner, owner_cik, code, ad, shares, price, ev, kn in cur.fetchall():
            items.append({"source_class": "insider", "actor": owner, "actor_kind": "insider", "actor_id": owner_cik,
                          "detail": {"transaction_code": code, "acquired_disposed": ad,
                                     "shares": float(shares) if shares is not None else None,
                                     "price_per_share": float(price) if price is not None else None},
                          **_staleness(ev, kn)})
        cur.execute(
            """SELECT f.id, f.name, s.form_type, s.activist, s.parse_confidence, s.event_time, s.knowable_time
               FROM stake_events s JOIN entities f ON f.id = s.filer_entity
               WHERE s.issuer_entity = %s ORDER BY s.knowable_time DESC LIMIT %s""",
            (eid, limit),
        )
        for fid, filer, form_type, activist, conf, ev, kn in cur.fetchall():
            items.append({"source_class": "activist" if activist else "passive_stake", "actor": filer,
                          "actor_kind": "institution", "actor_id": fid,
                          "detail": {"form_type": form_type, "percent_owned": None, "parse_confidence": conf},
                          **_staleness(ev, kn)})
        cur.execute(
            """SELECT f.id, f.name, h.value_usd, h.shares, h.share_type, h.period_end, h.knowable_time
               FROM fund_holdings h JOIN entities f ON f.id = h.filer_entity
               WHERE h.issuer_entity = %s ORDER BY h.knowable_time DESC LIMIT %s""",
            (eid, limit),
        )
        for fid, filer, value, shares, st, ev, kn in cur.fetchall():
            items.append({"source_class": "institutional_holding", "actor": filer,
                          "actor_kind": "institution", "actor_id": fid,
                          "detail": {"value_usd": float(value) if value is not None else None,
                                     "shares": float(shares) if shares is not None else None, "share_type": st},
                          **_staleness(ev, kn)})
        cur.execute(
            """SELECT settlement_date, knowable_time, current_short, change_short, days_to_cover
               FROM short_interest WHERE issuer_entity = %s ORDER BY knowable_time DESC LIMIT %s""",
            (eid, limit),
        )
        for settle, kn, cur_s, chg, dtc in cur.fetchall():
            items.append({"source_class": "short_interest", "actor": "FINRA consolidated",
                          "detail": {"current_short": float(cur_s) if cur_s is not None else None,
                                     "change_short": float(chg) if chg is not None else None,
                                     "days_to_cover": float(dtc) if dtc is not None else None},
                          **_staleness(settle, kn)})
    items.sort(key=lambda it: it["knowable_time"], reverse=True)
    return {"symbol": symbol.upper(), "resolved": True, "entity": {"id": eid, "cik": cik, "name": name},
            "source_classes": sorted({it["source_class"] for it in items}), "activity": items[:limit]}


# --------------------------------------------------------------------- signal surface

@app.get("/api/clusters")
def clusters(as_of: str = "latest", min_confidence: str = "medium", source_class: str = "",
             tos_session: str | None = Cookie(None)) -> dict:
    min_rank = _BUCKET_RANK.get(min_confidence, 1)
    with db.connect() as conn, conn.cursor() as cur:
        tier = _tier_of(conn, tos_session)
        aso = _effective_as_of(cur, as_of, tier)
        if aso is None:
            return {"as_of": None, "min_confidence": min_confidence, "calibration": CALIBRATION_PENDING,
                    "clusters": [], "tier": tier, "delayed_hours": authn.delay_hours(tier)}
        cur.execute(
            """SELECT c.issuer_entity, e.name, c.score, c.confidence_bucket, c.voices, c.source_classes,
                      (c.inputs->>'definition_version')::int,
                      c.inputs->>'freshest_knowable', c.inputs->>'stalest_knowable',
                      (c.inputs->'liquidity_floor'->>'ok'),
                      (SELECT symbol FROM security_map m WHERE m.entity_id = c.issuer_entity
                         AND m.source = 'sec_company_tickers' ORDER BY confidence DESC LIMIT 1)
               FROM signal_clusters c JOIN entities e ON e.id = c.issuer_entity
               WHERE c.as_of = %s AND (%s = '' OR %s = ANY(c.source_classes)) ORDER BY c.score DESC""",
            (aso, source_class, source_class),
        )
        out, defver = [], None
        for issuer, name, score, bucket, voices, classes, dv, fresh, stale, floor, symbol in cur.fetchall():
            if _BUCKET_RANK[bucket] < min_rank:
                continue
            defver = dv
            out.append({
                "issuer_entity": issuer, "symbol": symbol, "name": name,
                "score": float(score), "smart_money_score": presentation.smart_money_score(float(score)),
                "confidence_bucket": bucket,
                "voices": voices, "source_classes": classes, "definition_version": dv,
                "freshest_contributing_knowable": fresh, "stalest_contributing_knowable": stale,
                "above_liquidity_floor": floor == "true",
            })
    return {"as_of": aso.isoformat(), "min_confidence": min_confidence,
            "definition_version": defver, "clusters": out,
            "tier": tier, "delayed_hours": authn.delay_hours(tier)}


def _build_cluster_detail(cur, issuer_id: int, aso) -> dict:
    if aso is None:
        return {"found": False, "issuer_id": issuer_id}
    cur.execute(
        """SELECT c.id, c.score, c.confidence_bucket, c.voices, c.source_classes, c.inputs, c.as_of, e.name, e.cik
           FROM signal_clusters c JOIN entities e ON e.id = c.issuer_entity
           WHERE c.issuer_entity = %s AND c.as_of = %s""",
        (issuer_id, aso),
    )
    r = cur.fetchone()
    if r is None:
        return {"found": False, "issuer_id": issuer_id}
    cid, score, bucket, voices, classes, inputs, aso2, name, cik = r
    cur.execute(
        """SELECT slug, title FROM library_entries WHERE linked_source_classes && %s
           ORDER BY kind, title LIMIT 6""",
        (classes,),
    )
    library_links = [{"slug": s, "title": t} for s, t in cur.fetchall()]
    contributions = inputs.get("contributions", [])
    story = presentation.cluster_story(contributions, _voice_names(cur, [contributions]))
    return {
        "found": True, "cluster_id": cid, "issuer_entity": issuer_id, "symbol": _symbol_for(cur, issuer_id),
        "name": name, "cik": cik, "as_of": aso2.isoformat(), "score": float(score),
        "smart_money_score": presentation.smart_money_score(float(score)), "story": story,
        "confidence_bucket": bucket, "voices": voices,
        "source_classes": classes, "definition_version": inputs.get("definition_version"), "inputs": inputs,
        "library_links": library_links,
    }


@app.get("/api/clusters/{issuer_id}")
def cluster_detail(issuer_id: int, as_of: str = "latest", tos_session: str | None = Cookie(None)) -> dict:
    with db.connect() as conn:
        with conn.cursor() as cur:
            user = authn.session_user(conn, tos_session)
            tier = (user or {}).get("tier", "free")
            aso = _effective_as_of(cur, as_of, tier)
            detail = _build_cluster_detail(cur, issuer_id, aso)
        if user and tier == "admin" and detail.get("found"):
            with conn.cursor() as cur:  # log admin reads of not-yet-public clusters (staff-trading seed)
                cur.execute("SELECT %s > now() - make_interval(hours => %s)", (aso, authn.FREE_DELAY_HOURS))
                if cur.fetchone()[0]:
                    authn.audit(conn, user["email"], "prepub_access", detail.get("symbol") or str(issuer_id),
                                {"as_of": detail["as_of"], "issuer_entity": issuer_id})
    return detail


@app.get("/api/clusters/{issuer_id}/explanation")
def cluster_explanation(issuer_id: int, horizon: int = 30, provider: str | None = None,
                        tos_session: str | None = Cookie(None)) -> dict:
    from .backtest.run import compute_calibration
    from .explain.base import explain, to_dict
    with db.connect() as conn:
        with conn.cursor() as cur:
            tier = _tier_of(conn, tos_session)
            detail = _build_cluster_detail(cur, issuer_id, _effective_as_of(cur, "latest", tier))
        if not detail.get("found"):
            return {"found": False, "issuer_id": issuer_id}
        cal = compute_calibration(conn)
        exp = explain(conn, detail, cal, provider=provider, horizon=horizon)
    return {"found": True, "issuer_entity": issuer_id, "horizon": horizon, **to_dict(exp)}


@app.get("/api/calibration")
def calibration() -> dict:
    """Backtested calibration per confidence bucket per horizon — with honest exclusion and
    open-horizon counts. Buckets under the minimum episode sample read 'insufficient sample',
    never a bare rate. This is the data behind the 'Backtested' labels and the methodology page."""
    from .backtest.run import compute_calibration
    with db.connect() as conn:
        return compute_calibration(conn)


@app.get("/api/definitions")
def definitions() -> dict:
    with db.connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT name, version, params, code_hash, changelog, created_at FROM signal_definitions ORDER BY name, version"
        )
        defs = [{"name": n, "version": v, "params": p, "code_hash": h, "changelog": c,
                 "created_at": ca.isoformat()} for n, v, p, h, c, ca in cur.fetchall()]
    return {
        "definitions": defs,
        "note": ("Public methodology. Confidence buckets show backtested hit rates per horizon where the "
                 "resolved-episode sample is sufficient (min 30 episodes), and read 'insufficient sample' "
                 "otherwise; higher-conviction buckets remain sample-limited by historical price coverage."),
    }


@app.get("/api/home")
def home(min_confidence: str = "medium", limit: int = 40, tos_session: str | None = Cookie(None)) -> dict:
    """The consumer feed — "Smart Money Today". Today's convergences ranked by Smart Money
    Score, each with the plain-language story of who is piling in (named where the filing makes
    it public) and how fresh it is. Tier-delay aware (free sees the 48h-old set). Backtested
    rates are attached client-side from /api/calibration; nothing here promises returns."""
    min_rank = _BUCKET_RANK.get(min_confidence, 1)
    limit = max(1, min(100, limit))
    with db.connect() as conn, conn.cursor() as cur:
        tier = _tier_of(conn, tos_session)
        aso = _effective_as_of(cur, "latest", tier)
        if aso is None:
            return {"as_of": None, "tier": tier, "delayed_hours": authn.delay_hours(tier), "count": 0, "feed": []}
        cur.execute(
            """SELECT c.issuer_entity, e.name, c.score, c.confidence_bucket, c.voices, c.source_classes, c.inputs,
                      (SELECT symbol FROM security_map m WHERE m.entity_id = c.issuer_entity
                         AND m.source = 'sec_company_tickers' ORDER BY confidence DESC LIMIT 1)
               FROM signal_clusters c JOIN entities e ON e.id = c.issuer_entity
               WHERE c.as_of = %s ORDER BY c.score DESC""",
            (aso,),
        )
        rows = [r for r in cur.fetchall() if _BUCKET_RANK[r[3]] >= min_rank][:limit]
        names = _voice_names(cur, [(r[6] or {}).get("contributions", []) for r in rows])
        feed = []
        for issuer, name, score, bucket, voices, classes, inputs, symbol in rows:
            story = presentation.cluster_story((inputs or {}).get("contributions", []), names)
            feed.append({
                "issuer_entity": issuer, "symbol": symbol, "name": name,
                "smart_money_score": presentation.smart_money_score(float(score)),
                "score": float(score), "confidence_bucket": bucket,
                "voices": voices, "source_classes": classes,
                "headline": story["headline"], "story": story,
                "freshest_contributing_knowable": (inputs or {}).get("freshest_knowable"),
                "stalest_contributing_knowable": (inputs or {}).get("stalest_knowable"),
            })
    return {"as_of": aso.isoformat(), "tier": tier, "delayed_hours": authn.delay_hours(tier),
            "count": len(feed), "feed": feed}


@app.get("/api/leaderboards")
def leaderboards(tos_session: str | None = Cookie(None)) -> dict:
    """Consumer leaderboards built only from public filings, anchored to the most recent data
    actually on hand (not wall-clock), so windows are never empty and never overstated."""
    with db.connect() as conn, conn.cursor() as cur:
        tier = _tier_of(conn, tos_session)
        cur.execute(
            """SELECT t.issuer_entity, e.name,
                      (SELECT symbol FROM security_map m WHERE m.entity_id=t.issuer_entity
                         AND m.source='sec_company_tickers' ORDER BY confidence DESC LIMIT 1) AS symbol,
                      count(DISTINCT t.owner_cik) AS buyers
               FROM insider_transactions t JOIN entities e ON e.id=t.issuer_entity
               WHERE t.transaction_code='P' AND t.acquired_disposed='A' AND t.issuer_entity IS NOT NULL
                 AND t.knowable_time > (SELECT max(knowable_time) FROM insider_transactions) - interval '30 days'
               GROUP BY t.issuer_entity, e.name HAVING count(DISTINCT t.owner_cik) >= 2
               ORDER BY buyers DESC, e.name LIMIT 12""",
        )
        most_bought = [{"issuer_entity": i, "name": n, "symbol": s, "buyers": b} for i, n, s, b in cur.fetchall()]
        cur.execute(
            """SELECT s.filer_entity, f.name AS filer, s.issuer_entity, e.name AS issuer,
                      (SELECT symbol FROM security_map m WHERE m.entity_id=s.issuer_entity
                         AND m.source='sec_company_tickers' ORDER BY confidence DESC LIMIT 1) AS symbol,
                      s.knowable_time
               FROM stake_events s JOIN entities f ON f.id=s.filer_entity JOIN entities e ON e.id=s.issuer_entity
               WHERE s.form_type='SCHEDULE 13D' AND s.issuer_entity IS NOT NULL
               ORDER BY s.knowable_time DESC LIMIT 12""",
        )
        new_activist = [{"filer_entity": fe, "filer": f, "issuer_entity": ie, "issuer": iss,
                         "symbol": sym, "knowable_time": kn.isoformat()}
                        for fe, f, ie, iss, sym, kn in cur.fetchall()]
        aso = _effective_as_of(cur, "latest", tier)
        top = []
        if aso is not None:
            cur.execute(
                """SELECT c.issuer_entity, e.name, c.score, c.confidence_bucket,
                          (SELECT symbol FROM security_map m WHERE m.entity_id=c.issuer_entity
                             AND m.source='sec_company_tickers' ORDER BY confidence DESC LIMIT 1)
                   FROM signal_clusters c JOIN entities e ON e.id=c.issuer_entity
                   WHERE c.as_of=%s ORDER BY c.score DESC LIMIT 12""",
                (aso,),
            )
            top = [{"issuer_entity": i, "name": n, "symbol": s,
                    "smart_money_score": presentation.smart_money_score(float(sc)), "confidence_bucket": b}
                   for i, n, sc, b, s in cur.fetchall()]
    return {"most_bought": most_bought, "new_activist_stakes": new_activist, "top_convergence": top,
            "note": "Built from public SEC filings, anchored to the most recent data on hand. "
                    "Counts and stakes are facts from the filings; nothing here is advice."}


@app.get("/api/brief")
def morning_brief(tos_session: str | None = Cookie(None)) -> dict:
    """The Morning Brief — the day's cross-plane intelligence in one place: an AI executive summary,
    impact-ranked cited news ('what changed overnight'), the smart-money convergence digest, and — when
    signed in — the names you follow. Tier-delay aware on the signal portion; degrades to deterministic
    prose so it is never blocked on a model being up. Cached per (user, day) by an inputs-hash."""
    provider = os.environ.get("EXPLAIN_PROVIDER", "template")
    with db.connect() as conn:
        user = authn.session_user(conn, tos_session)
        tier = (user or {}).get("tier", "free")
        with conn.cursor() as cur:
            as_of = _effective_as_of(cur, "latest", tier)
        followed: list[str] = []
        if user:
            with conn.cursor() as cur:
                cur.execute("SELECT ref FROM follows WHERE user_id=%s AND kind='symbol'", (user["id"],))
                followed = [r[0] for r in cur.fetchall()]
        return brief_mod.cached_compose(
            conn, user_id=(user or {}).get("id"), as_of=as_of, tier=tier,
            delayed_hours=authn.delay_hours(tier), followed_symbols=followed,
            provider=provider, voice_name_fn=_voice_names)


@app.get("/api/dashboard")
def dashboard(tos_session: str | None = Cookie(None)) -> dict:
    """The Dashboard — the calm command center. One call returns the Market Pulse (a transparent
    flow-and-positioning read with its own drivers), today's biggest smart-money opportunities, the
    impact-ranked news that matters now, the smart-money digest, and what's on the radar. Tier-delay
    aware on the signal plane; assembled from real records only and safe on empty data."""
    provider = os.environ.get("EXPLAIN_PROVIDER", "template")
    with db.connect() as conn:
        user = authn.session_user(conn, tos_session)
        tier = (user or {}).get("tier", "free")
        with conn.cursor() as cur:
            as_of = _effective_as_of(cur, "latest", tier)
        followed: list[str] = []
        if user:
            with conn.cursor() as cur:
                cur.execute("SELECT ref FROM follows WHERE user_id=%s AND kind='symbol'", (user["id"],))
                followed = [r[0] for r in cur.fetchall()]
        return dashboard_mod.compose(
            conn, as_of=as_of, tier=tier, delayed_hours=authn.delay_hours(tier),
            followed_symbols=followed, provider=provider, voice_name_fn=_voice_names)


@app.get("/api/events")
def events_calendar(days: int = 10) -> dict:
    """Event & Macro Intelligence — the forward calendar (upcoming earnings + US macro releases), grouped
    by day, with a deterministic 'why it matters / which sectors' read on macro events and cross-plane
    flags (smart-money / attention) on company earnings. Public data, not tier-gated."""
    from .ingestion import calendar_nasdaq
    days = max(1, min(21, days))
    with db.connect() as conn:
        return {"days": days, "calendar": events_mod.by_day(conn, days),
                "sources": calendar_nasdaq.sources_status()}


@app.get("/api/jobs")
def jobs_status() -> dict:
    """Continuous-update health: the last run + status per scheduler job, so freshness is observable
    (and a stalled worker is visible, not silently stale)."""
    with db.connect() as conn:
        return {"jobs": scheduler_mod.job_status(conn)}


@app.get("/api/news")
def news_feed(symbol: str | None = None, category: str | None = None, hours: int = 72, limit: int = 40) -> dict:
    """Impact-ranked News Intelligence — SEC 8-K material events + market/macro headlines, each with the
    analyst's cited 'why it matters' when analyzed. Public info, so not tier-delayed."""
    limit = max(1, min(100, limit))
    with db.connect() as conn:
        window = news_mod.ranked_news_window(conn, symbol=symbol, category=category, hours=hours,
                                             limit=limit)
        return {**window, "sources": news_mod.sources_status(conn)}


@app.get("/api/news/coverage")
def news_coverage(hours: int = 96, limit: int = 12) -> dict:
    """How differently outlets frame the same event, and where coverage is thin.

    Both halves come out of the spine's clustering for free. The comparison is only meaningful
    because the feed list deliberately spans outlets in different countries — two CNBC feeds
    agreeing is not two perspectives, which is what this view showed before those were added."""
    hours, limit = max(6, min(720, hours)), max(1, min(40, limit))
    with db.connect() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT c.id, c.title, c.category, c.source_count, c.event_count, c.novelty_score,
                      json_agg(json_build_object('source', e.source, 'title', e.title,
                                                 'url', e.source_url, 'geo', e.geo)
                               ORDER BY e.knowable_time) AS reports
                 FROM event_clusters c JOIN events e ON e.cluster_id = c.id
                WHERE c.last_seen >= now() - make_interval(hours => %s)
                  AND c.source_count > 1
             GROUP BY c.id
               HAVING count(DISTINCT regexp_replace(split_part(e.source, '/', 2), '-.*$', '')) > 1
             ORDER BY count(DISTINCT regexp_replace(split_part(e.source, '/', 2), '-.*$', '')) DESC,
                      c.novelty_score DESC NULLS LAST
                LIMIT %s""", (hours, limit))
        cols = ("id", "title", "category", "source_count", "event_count", "novelty", "reports")
        compared = [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

        # Thin coverage: high novelty, reported by one outlet only. The brief asks for "where
        # coverage is unusually thin relative to an event's significance" — this is that, and it is
        # the more interesting half, because a story only one outlet is carrying is either early or
        # being ignored.
        cur.execute(
            """SELECT c.id, c.title, c.category, c.novelty_score,
                      min(e.source) AS only_source, min(e.source_url) AS url
                 FROM event_clusters c JOIN events e ON e.cluster_id = c.id
                WHERE c.last_seen >= now() - make_interval(hours => %s)
                  AND c.source_count = 1
                  AND coalesce(c.novelty_score, 0) >= 0.45
             GROUP BY c.id
             ORDER BY c.novelty_score DESC LIMIT %s""", (hours, limit))
        tcols = ("id", "title", "category", "novelty", "only_source", "url")
        thin = [dict(zip(tcols, r, strict=True)) for r in cur.fetchall()]

        cur.execute("""SELECT count(DISTINCT regexp_replace(split_part(source, '/', 2), '-.*$', ''))
                         FROM events WHERE source LIKE 'rss/%%'""")
        outlets = cur.fetchone()[0]

    return {
        "compared": compared, "thin_coverage": thin, "distinct_outlets": outlets, "hours": hours,
        "note": ("A story carried by one outlet is not necessarily unimportant — it may be early, "
                 "or outside what the connected feeds cover well. Coverage breadth measures this "
                 "product's reach as much as an event's significance."),
    }


@app.get("/api/news/{news_id}")
def news_item(news_id: int) -> dict:
    with db.connect() as conn:
        it = news_mod.get_item(conn, news_id)
        return {"found": True, **it} if it else {"found": False}


@app.get("/api/asset/{symbol}")
def asset(symbol: str) -> dict:
    """Deep-dive bundle for one name: cluster history, recent prices (with cluster markers by
    date), and this issuer's own backtested stats when it has at least 5 resolved episodes."""
    sym = symbol.strip().upper()
    with db.connect() as conn, conn.cursor() as cur:
        ent = _resolve_symbol(cur, sym)
        if ent is None:
            return {"resolved": False, "symbol": sym}
        eid, cik, name = ent
        cur.execute(
            "SELECT id, as_of, score, confidence_bucket FROM signal_clusters WHERE issuer_entity=%s ORDER BY as_of",
            (eid,),
        )
        history = [{"cluster_id": r[0], "as_of": r[1].isoformat(), "score": float(r[2]), "bucket": r[3]}
                   for r in cur.fetchall()]
        cur.execute("SELECT day, close FROM prices_eod WHERE symbol=%s ORDER BY day DESC LIMIT 130", (sym,))
        prices = [{"day": d.isoformat(), "close": float(c)} for d, c in reversed(cur.fetchall())]
        cur.execute(
            """SELECT count(o.excess_30), avg(CASE WHEN o.excess_30>0 THEN 1.0 ELSE 0 END)
               FROM signal_outcomes o JOIN signal_clusters c ON c.id=o.cluster_id
               WHERE c.issuer_entity=%s AND o.excess_30 IS NOT NULL""",
            (eid,),
        )
        n, hr = cur.fetchone()
    stats = {"episodes_30d": int(n or 0),
             "hit_rate_30d": round(float(hr), 3) if (n and n >= 5) else None,
             "sufficient": bool(n and n >= 5)}
    return {"resolved": True, "symbol": sym, "entity": {"id": eid, "cik": cik, "name": name},
            "current_cluster": history[-1] if history else None,
            "cluster_history": history, "prices": prices, "name_stats": stats}


@app.get("/api/institution/{entity_id}")
def institution(entity_id: int, limit: int = 100) -> dict:
    """A filer's disclosed positioning over time — every figure carrying its knowable-time lag."""
    with db.connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT name, cik, kind FROM entities WHERE id=%s", (entity_id,))
        r = cur.fetchone()
        if r is None:
            return {"found": False, "entity_id": entity_id}
        name, cik, kind = r
        cur.execute(
            """SELECT s.form_type, s.event_time, s.knowable_time, e.name,
                      (SELECT symbol FROM security_map m WHERE m.entity_id=s.issuer_entity AND m.source='sec_company_tickers' LIMIT 1)
               FROM stake_events s JOIN entities e ON e.id=s.issuer_entity
               WHERE s.filer_entity=%s ORDER BY s.knowable_time DESC LIMIT %s""",
            (entity_id, limit),
        )
        stakes = [{"form_type": ft, "issuer": nm, "symbol": sy, **_staleness(ev, kn)}
                  for ft, ev, kn, nm, sy in cur.fetchall()]
        cur.execute(
            """SELECT e.name, (SELECT symbol FROM security_map m WHERE m.entity_id=h.issuer_entity AND m.source='sec_company_tickers' LIMIT 1),
                      h.value_usd, h.shares, h.period_end, h.knowable_time
               FROM fund_holdings h JOIN entities e ON e.id=h.issuer_entity
               WHERE h.filer_entity=%s AND h.period_end=(SELECT max(period_end) FROM fund_holdings WHERE filer_entity=%s)
               ORDER BY h.value_usd DESC NULLS LAST LIMIT %s""",
            (entity_id, entity_id, limit),
        )
        holdings = [{"issuer": nm, "symbol": sy, "value_usd": float(v) if v is not None else None,
                     "shares": float(sh) if sh is not None else None, **_staleness(pe, kn)}
                    for nm, sy, v, sh, pe, kn in cur.fetchall()]
    return {"found": True, "entity_id": entity_id, "name": name, "cik": cik, "kind": kind,
            "stakes": stakes, "top_holdings": holdings}


@app.get("/api/insider/{owner_cik}")
def insider(owner_cik: str, limit: int = 100) -> dict:
    """An insider's disclosed transactions over time across issuers."""
    with db.connect() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT owner_name, issuer_name,
                      (SELECT symbol FROM security_map m WHERE m.entity_id=t.issuer_entity AND m.source='sec_company_tickers' LIMIT 1),
                      transaction_code, acquired_disposed, shares, price_per_share, event_time, knowable_time
               FROM insider_transactions t WHERE owner_cik=%s ORDER BY knowable_time DESC LIMIT %s""",
            (owner_cik, limit),
        )
        rows = cur.fetchall()
        if not rows:
            return {"found": False, "owner_cik": owner_cik}
        name = rows[0][0]
        txns = [{"issuer": iss, "symbol": sy, "transaction_code": code, "acquired_disposed": ad,
                 "shares": float(sh) if sh is not None else None,
                 "price_per_share": float(p) if p is not None else None, **_staleness(ev, kn)}
                for _n, iss, sy, code, ad, sh, p, ev, kn in rows]
    return {"found": True, "owner_cik": owner_cik, "name": name, "transactions": txns}


@app.post("/api/extract-tickers")
async def extract_tickers_endpoint(request: Request) -> dict:
    """Screenshot -> tickers ONLY (Feature Spec 5.5 / docs/threat-models/screenshot.md). The
    image is processed in-request and never stored; only symbols are returned; only the fact of
    an extraction is logged, never contents."""
    if not _rate_ok():
        return {"error": "rate limited; try again shortly", "recognized": [], "unrecognized": []}
    mime = request.headers.get("content-type", "").split(";")[0].strip()
    if mime not in _ALLOWED_IMAGE:
        return {"error": "unsupported content-type; use png, jpeg, or webp", "recognized": [], "unrecognized": []}
    body = await request.body()
    if not body or len(body) > MAX_IMAGE_BYTES:
        return {"error": "image missing or larger than 8MB", "recognized": [], "unrecognized": []}

    from .explain.base import extract_tickers
    candidates = extract_tickers(body, mime)  # already passed the ^[A-Z.]{1,6}$ output guard
    log.info("extract-tickers: %d candidate symbols (image not stored)", len(candidates))

    recognized, unrecognized = [], []
    with db.connect() as conn, conn.cursor() as cur:
        for sym in candidates:
            cur.execute(
                "SELECT 1 FROM security_map WHERE symbol=%s AND source='sec_company_tickers' LIMIT 1",
                (sym,),
            )
            (recognized if cur.fetchone() else unrecognized).append(sym)
    return {"recognized": recognized, "unrecognized": unrecognized,
            "note": "Symbols only. The image was processed in-request and not stored; no prices or "
                    "positions were read.",
            "provider_available": bool(candidates) or None}


# ------------------------------------------------------------------- trade journal (Slice E)

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


def _num(x):
    return float(x) if isinstance(x, (int, float)) and x >= 0 else None


def _pdate(s):
    try:
        return date.fromisoformat(s[:10]) if s else None
    except ValueError:
        return None


def _txt(x, n):
    return ((x or "").strip()[:n]) or None


def _sanitize_trade(req: TradeReq, cur) -> dict:
    """Validate enums, clamp text/numbers, resolve symbol->entity. Field names are fixed internal
    identifiers (never user input), so building the column list from them is injection-safe."""
    sym = _txt(req.symbol, 12)
    sym = sym.upper() if sym else None
    ent = _resolve_symbol(cur, sym) if sym else None
    return {
        "symbol": sym, "entity_id": ent[0] if ent else None,
        "asset_class": req.asset_class if req.asset_class in _ASSET else "equity",
        "direction": req.direction if req.direction in _DIR else "long",
        "status": req.status if req.status in _STATUS else "planned",
        "entry_price": _num(req.entry_price), "exit_price": _num(req.exit_price),
        "stop_price": _num(req.stop_price), "target_price": _num(req.target_price),
        "size": _num(req.size), "size_unit": req.size_unit if req.size_unit in _UNIT else "shares",
        "timeframe": _txt(req.timeframe, 24), "strategy": _txt(req.strategy, 48),
        "reason_entry": _txt(req.reason_entry, 2000), "reason_exit": _txt(req.reason_exit, 2000),
        "confidence": req.confidence if req.confidence in (1, 2, 3, 4, 5) else None,
        "expected_outcome": _txt(req.expected_outcome, 500),
        "opened_on": _pdate(req.opened_on), "closed_on": _pdate(req.closed_on),
        "is_public": bool(req.is_public),
    }


def _trade_to_dict(row) -> dict:
    m = dict(zip(_TRADE_COLS, row, strict=True))
    d = m["direction"]
    m["reward_risk"] = trades.reward_risk(m["entry_price"], m["stop_price"], m["target_price"], d)
    m["rr"] = m["reward_risk"]  # alias consumed by summarize_performance
    m["realized_pnl_pct"] = (trades.realized_pnl_pct(m["entry_price"], m["exit_price"], d)
                             if m["status"] == "closed" else None)
    m["has_image"] = bool(m.pop("image_path"))
    for k in ("opened_on", "closed_on", "created_at", "updated_at"):
        if m.get(k) is not None:
            m[k] = m[k].isoformat()
    m.pop("user_id", None)
    return m


def _load_trade(cur, tid: int):
    cur.execute(sql.SQL("SELECT {cols} FROM trades WHERE id=%s").format(cols=_TRADE_COL_SQL), (tid,))
    return cur.fetchone()


@app.post("/api/trades")
def trade_create(req: TradeReq, response: Response, tos_session: str | None = Cookie(None)) -> dict:
    with db.connect() as conn, conn.cursor() as cur:
        user = authn.session_user(conn, tos_session)
        if not user:
            response.status_code = 401
            return {"error": "log in to journal your trades"}
        max_t = billing.entitlements(user["tier"])["max_trades"]
        cur.execute("SELECT count(*) FROM trades WHERE user_id=%s", (user["id"],))
        if cur.fetchone()[0] >= max_t:
            response.status_code = 403
            return {"error": f"Your plan allows {max_t} journal entries. Upgrade for more.", "upgrade": True}
        f = _sanitize_trade(req, cur)
        cur.execute(
            sql.SQL("INSERT INTO trades (user_id, {cols}) VALUES (%s, {vals}) RETURNING id").format(
                cols=sql.SQL(", ").join(sql.Identifier(k) for k in f),
                vals=sql.SQL(", ").join(sql.Placeholder() * len(f))),
            (user["id"], *f.values()))
        tid = cur.fetchone()[0]
        conn.commit()

        # Freeze what the world was showing at this moment (Phase 6). Deliberately after the
        # commit and inside its own try: a journal entry the trader just wrote must never be lost
        # because the spine was empty, slow, or broken. Missing context degrades to "none
        # captured", which the interface states honestly.
        captured = None
        try:
            captured = journal_context.capture(
                conn, user["id"],
                {"id": tid, "symbol": f["symbol"], "direction": f["direction"]},
                datetime.now(UTC))
        except Exception as exc:
            log.warning("world context capture failed for trade %s (%s)", tid, type(exc).__name__)
    return {"created": True, "id": tid,
            "context": {"n_live": captured["n_live"], "n_on_symbol": captured["n_on_symbol"],
                        "alignment": captured["alignment"]} if captured else None}


@app.get("/api/trades")
def trades_list(user_id: int | None = None, tos_session: str | None = Cookie(None)) -> dict:
    """Own journal when authenticated; a profile's PUBLIC trades when `user_id` is given."""
    with db.connect() as conn, conn.cursor() as cur:
        me = authn.session_user(conn, tos_session)
        if user_id is not None:
            cur.execute(sql.SQL("SELECT {cols} FROM trades WHERE user_id=%s AND is_public "
                                "ORDER BY created_at DESC LIMIT 200").format(cols=_TRADE_COL_SQL),
                        (user_id,))
            return {"scope": "public", "trades": [_trade_to_dict(r) for r in cur.fetchall()]}
        if not me:
            return {"authenticated": False, "trades": []}
        cur.execute(sql.SQL("SELECT {cols} FROM trades WHERE user_id=%s "
                            "ORDER BY created_at DESC LIMIT 500").format(cols=_TRADE_COL_SQL),
                    (me["id"],))
        return {"authenticated": True, "trades": [_trade_to_dict(r) for r in cur.fetchall()]}


@app.get("/api/trades/{tid}")
def trade_get(tid: int, tos_session: str | None = Cookie(None)) -> dict:
    with db.connect() as conn, conn.cursor() as cur:
        me = authn.session_user(conn, tos_session)
        row = _load_trade(cur, tid)
        if not row:
            return {"found": False}
        m = dict(zip(_TRADE_COLS, row, strict=True))
        owner = bool(me and me["id"] == m["user_id"])
        if not m["is_public"] and not owner:
            return {"found": False}  # never reveal a private trade's existence
        cur.execute("SELECT handle FROM users WHERE id=%s", (m["user_id"],))
        author = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM trade_reactions WHERE trade_id=%s AND kind='like'", (tid,))
        likes = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM trade_comments WHERE trade_id=%s AND NOT hidden", (tid,))
        comments = cur.fetchone()[0]
        mine: set = set()
        if me:
            cur.execute("SELECT kind FROM trade_reactions WHERE trade_id=%s AND user_id=%s", (tid, me["id"]))
            mine = {r[0] for r in cur.fetchall()}
    return {"found": True, "owner": owner, "author": author, "likes": likes, "comments": comments,
            "my_reactions": sorted(mine), "trade": _trade_to_dict(row)}


@app.patch("/api/trades/{tid}")
def trade_update(tid: int, req: TradeReq, response: Response, tos_session: str | None = Cookie(None)) -> dict:
    with db.connect() as conn, conn.cursor() as cur:
        user = authn.session_user(conn, tos_session)
        if not user:
            response.status_code = 401
            return {"error": "not authenticated"}
        cur.execute("SELECT 1 FROM trades WHERE id=%s AND user_id=%s", (tid, user["id"]))
        if not cur.fetchone():
            response.status_code = 404
            return {"error": "trade not found"}
        f = _sanitize_trade(req, cur)
        cur.execute(
            sql.SQL("UPDATE trades SET {sets}, updated_at=now() WHERE id=%s AND user_id=%s").format(
                sets=sql.SQL(", ").join(
                    sql.SQL("{} = {}").format(sql.Identifier(k), sql.Placeholder()) for k in f)),
            (*f.values(), tid, user["id"]))
        cur.execute("DELETE FROM trade_analyses WHERE trade_id=%s", (tid,))  # inputs changed -> stale
        conn.commit()
    return {"updated": True}


@app.delete("/api/trades/{tid}")
def trade_delete(tid: int, response: Response, tos_session: str | None = Cookie(None)) -> dict:
    with db.connect() as conn, conn.cursor() as cur:
        user = authn.session_user(conn, tos_session)
        if not user:
            response.status_code = 401
            return {"error": "not authenticated"}
        cur.execute("SELECT image_path FROM trades WHERE id=%s AND user_id=%s", (tid, user["id"]))
        row = cur.fetchone()
        if not row:
            response.status_code = 404
            return {"error": "trade not found"}
        cur.execute("DELETE FROM trades WHERE id=%s AND user_id=%s", (tid, user["id"]))
        conn.commit()
    _delete_image(row[0])
    return {"deleted": True}


@app.get("/api/trades/{tid}/analysis")
def trade_analysis(tid: int, tos_session: str | None = Cookie(None)) -> dict:
    with db.connect() as conn, conn.cursor() as cur:
        me = authn.session_user(conn, tos_session)
        row = _load_trade(cur, tid)
        if not row:
            return {"found": False}
        m = dict(zip(_TRADE_COLS, row, strict=True))
        if not m["is_public"] and not (me and me["id"] == m["user_id"]):
            return {"found": False}
        # AI kill-switch: off -> deterministic template analysis, no LLM call
        provider = flags.effective_provider(conn, "ai_trade_analysis")
        analysis = trades.cached_analysis(conn, m, provider=provider)
    return {"found": True, "analysis": analysis}


@app.get("/api/trades/{tid}/context")
def trade_context(tid: int, tos_session: str | None = Cookie(None)) -> dict:
    """What the Radar was showing when this trade was logged. Owner-only.

    Stricter than the analysis route, which a published trade exposes to viewers: this snapshot is
    ranked by the OWNER's personal relevance, so it leaks their country, currency and watchlist.
    Publishing a trade is not consent to publish the frame you read the world through.
    """
    with db.connect() as conn, conn.cursor() as cur:
        user = authn.session_user(conn, tos_session)
        if not user:
            return {"found": False}
        cur.execute("SELECT 1 FROM trades WHERE id=%s AND user_id=%s", (tid, user["id"]))
        if not cur.fetchone():
            return {"found": False}
        ctx = journal_context.for_trade(conn, tid)
    if not ctx:
        return {"found": True, "context": None,
                "note": "No world context was captured for this trade — it was logged before the "
                        "journal started recording what the Radar was showing."}
    return {"found": True, "context": ctx}


@app.get("/api/trades/{tid}/chart-analysis")
def trade_chart_analysis(tid: int, refresh: int = 0, tos_session: str | None = Cookie(None)) -> dict:
    """Educational AI read of the chart screenshot on the user's OWN trade (owner-only — the image is
    private). Cached per trade and invalidated by the image hash; `refresh=1` re-runs it (e.g. after a
    vision model is connected). Falls back to the deterministic level-based analysis with no model."""
    import hashlib

    from .intelligence import vision
    with db.connect() as conn, conn.cursor() as cur:
        user = authn.session_user(conn, tos_session)
        if not user:
            return {"found": False, "error": "not authenticated"}
        row = _load_trade(cur, tid)
        if not row:
            return {"found": False}
        m = dict(zip(_TRADE_COLS, row, strict=True))
        if m["user_id"] != user["id"]:
            return {"found": False}                       # owner-only; never reveal another's trade
        if not m["image_path"]:
            return {"found": True, "has_image": False,
                    "note": "Upload a chart screenshot to this trade to get an AI read of it."}
        p = _image_path(m["image_path"])
        if not p or not p.exists():
            return {"found": True, "has_image": False}
        img = p.read_bytes()
        h = hashlib.sha256(img).hexdigest()
        cur.execute("SELECT image_hash, analysis FROM chart_analyses WHERE trade_id=%s", (tid,))
        cached = cur.fetchone()
        if cached and cached[0] == h and not refresh:
            return {"found": True, "has_image": True, "analysis": {**cached[1], "from_cache": True}}
        provider = flags.effective_provider(conn, "ai_trade_analysis")
        analysis = vision.analyze_chart(img, "image/png", trade=m, provider=provider)
        cur.execute(
            """INSERT INTO chart_analyses (trade_id, image_hash, analysis, model_id, used_template)
               VALUES (%s,%s,%s,%s,%s)
               ON CONFLICT (trade_id) DO UPDATE SET image_hash=EXCLUDED.image_hash,
                 analysis=EXCLUDED.analysis, model_id=EXCLUDED.model_id,
                 used_template=EXCLUDED.used_template, created_at=now()""",
            (tid, h, Json(analysis), analysis.get("model_id"), analysis.get("used_template")))
        conn.commit()
    return {"found": True, "has_image": True, "analysis": {**analysis, "from_cache": False}}


@app.post("/api/analyze-chart")
async def analyze_chart_standalone(request: Request, tos_session: str | None = Cookie(None)) -> dict:
    """Standalone educational read of any chart image (logged-in; uses the vision quota). Processed
    in-request and not stored. Same guards + honest fallback as the trade-attached analysis."""
    from .intelligence import vision
    with db.connect() as conn:
        user = authn.session_user(conn, tos_session)
        if not user:
            return {"error": "log in to analyze a chart"}
        provider = flags.effective_provider(conn, "ai_trade_analysis")
    mime = request.headers.get("content-type", "").split(";")[0].strip()
    if mime not in _ALLOWED_IMAGE:
        return {"error": "unsupported content-type; use png, jpeg, or webp"}
    body = await request.body()
    if not body or len(body) > MAX_IMAGE_BYTES:
        return {"error": "image missing or larger than 8MB"}
    analysis = vision.analyze_chart(body, mime, trade=None, provider=provider)
    return {"analysis": analysis, "note": "Image processed in-request and not stored."}


@app.get("/api/performance")
def performance(tos_session: str | None = Cookie(None)) -> dict:
    with db.connect() as conn, conn.cursor() as cur:
        user = authn.session_user(conn, tos_session)
        if not user:
            return {"authenticated": False}
        cur.execute(sql.SQL("SELECT {cols} FROM trades WHERE user_id=%s").format(cols=_TRADE_COL_SQL),
                    (user["id"],))
        rows = [_trade_to_dict(r) for r in cur.fetchall()]
    return {"authenticated": True, "summary": trades.summarize_performance(rows), "total": len(rows)}


# ------------------------------------------------------------------ advanced AI (Slice L)

@app.get("/api/trades/{tid}/similar")
def trade_similar(tid: int, tos_session: str | None = Cookie(None)) -> dict:
    """The OWNER's own trades most like this one, with an honest cohort outcome (descriptive history,
    not a prediction). Restricted to the owner — a viewer never sees another trader's private journal."""
    with db.connect() as conn, conn.cursor() as cur:
        me = authn.session_user(conn, tos_session)
        row = _load_trade(cur, tid)
        if not row:
            return {"found": False}
        m = dict(zip(_TRADE_COLS, row, strict=True))
        if not (me and me["id"] == m["user_id"]):
            return {"found": False}
        target = {"id": m["id"], "symbol": m["symbol"], "direction": m["direction"],
                  "asset_class": m["asset_class"], "strategy": m["strategy"], "timeframe": m["timeframe"],
                  "reward_risk": trades.reward_risk(m["entry_price"], m["stop_price"], m["target_price"], m["direction"])}
        res = insights.similar_for_trade(conn, target, me["id"])
    return {"found": True, **res}


@app.post("/api/simulate")
def simulate_endpoint(req: SimulateReq, response: Response, tos_session: str | None = Cookie(None)) -> dict:
    """Deterministic position scenario simulator (docs/threat-models/insights.md): P&L, R-multiple and
    account-risk across price points the user names, plus a signal base-rate overlay when the symbol
    maps to a real convergence signal — never a probability or a forecast for the trade."""
    if not _rate_ok(limit=30):
        response.status_code = 429
        return {"ok": False, "reason": "slow down a moment and try again"}
    with db.connect() as conn, conn.cursor() as cur:
        user = authn.session_user(conn, tos_session)
        if not user:
            response.status_code = 401
            return {"ok": False, "reason": "log in to use the simulator"}
        entity_id = None
        if req.symbol:
            ent = _resolve_symbol(cur, req.symbol)
            entity_id = ent[0] if ent else None
        trade = {"entry_price": req.entry_price, "stop_price": req.stop_price,
                 "target_price": req.target_price, "direction": req.direction,
                 "size": req.size, "size_unit": req.size_unit,
                 "symbol": (req.symbol or "").strip().upper() or None}
        return insights.simulate_with_context(conn, trade, req.account_size, entity_id)


@app.get("/api/journal/report")
def journal_report_endpoint(tos_session: str | None = Cookie(None)) -> dict:
    """Auto journal report over the user's OWN journal — aggregate performance + recurring habits,
    optionally phrased by the guarded model (AI kill-switch honored), cached by an inputs-hash."""
    with db.connect() as conn:
        user = authn.session_user(conn, tos_session)
        if not user:
            return {"authenticated": False}
        provider = flags.effective_provider(conn, "ai_trade_analysis")
        report = insights.journal_report(conn, user["id"], provider=provider)
    return {"authenticated": True, "report": report}


@app.post("/api/trades/{tid}/image")
async def trade_image_upload(tid: int, request: Request, tos_session: str | None = Cookie(None)):
    if not _rate_ok():
        return JSONResponse({"error": "rate limited; try again shortly"}, status_code=429)
    mime = request.headers.get("content-type", "").split(";")[0].strip()
    if mime not in _ALLOWED_IMAGE:
        return JSONResponse({"error": "unsupported content-type; use png, jpeg, or webp"}, status_code=400)
    body = await request.body()
    if not body or len(body) > MAX_IMAGE_BYTES:
        return JSONResponse({"error": "image missing or larger than 8MB"}, status_code=400)
    with db.connect() as conn, conn.cursor() as cur:
        user = authn.session_user(conn, tos_session)
        if not user:
            return JSONResponse({"error": "not authenticated"}, status_code=401)
        cur.execute("SELECT image_path FROM trades WHERE id=%s AND user_id=%s", (tid, user["id"]))
        row = cur.fetchone()
        if not row:
            return JSONResponse({"error": "trade not found"}, status_code=404)
        try:
            key = _store_image(body)
        except Exception:
            return JSONResponse({"error": "could not read that image"}, status_code=400)
        cur.execute("UPDATE trades SET image_path=%s, updated_at=now() WHERE id=%s AND user_id=%s",
                    (key, tid, user["id"]))
        conn.commit()
    if row[0] and row[0] != key:
        _delete_image(row[0])
    return {"uploaded": True}


@app.get("/api/trades/{tid}/image")
def trade_image(tid: int, tos_session: str | None = Cookie(None)):
    with db.connect() as conn, conn.cursor() as cur:
        me = authn.session_user(conn, tos_session)
        cur.execute("SELECT user_id, is_public, image_path FROM trades WHERE id=%s", (tid,))
        r = cur.fetchone()
    if not r or not r[2]:
        return Response(status_code=404)
    uid, pub, key = r
    if not pub and not (me and me["id"] == uid):
        return Response(status_code=404)
    p = _image_path(key)
    if not p or not p.exists():
        return Response(status_code=404)
    return Response(p.read_bytes(), media_type="image/png",
                    headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"})


@app.post("/api/assistant")
def assistant_endpoint(req: AssistantReq, response: Response, tos_session: str | None = Cookie(None)) -> dict:
    """Grounded, guarded Q&A over real platform data (docs/threat-models/assistant.md). Tier-honest
    (clusters read at the tier's effective as_of) and object-scoped (only the requester's trades)."""
    if not _rate_ok(limit=15):
        response.status_code = 429
        return {"answer": "I'm getting a lot of questions right now — try again in a moment.",
                "sources": [], "model_id": "template", "used_template": True}
    q = (req.message or "").strip()[:500]
    if not q:
        return {"answer": "Ask me about a ticker's smart-money signal, a strategy or concept from the "
                          "library, or your own logged trades.", "sources": [], "model_id": "template",
                "used_template": True}
    with db.connect() as conn:
        with conn.cursor() as cur:
            user = authn.session_user(conn, tos_session)
            tier = (user or {}).get("tier", "free")
            as_of = _effective_as_of(cur, "latest", tier)
        # AI kill-switch: when the flag is off, force the deterministic grounded answer (no LLM call)
        provider = flags.effective_provider(conn, "ai_assistant")
        return assistant.answer(conn, q, user, as_of, provider=provider)


@app.get("/api/trending")
def trending_endpoint(hours: int = 72) -> dict:
    """Social & Attention Intelligence: names ranked by public-attention velocity across connected
    sources (Wikipedia + Hacker News now; Reddit when its free key is set), with the analyst's 'why it's
    drawing attention' connecting each spike to its likely news catalyst. Honest source-status map;
    public data, not tier-gated; never fabricated."""
    hours = max(6, min(336, hours))
    with db.connect() as conn:
        board = social_mod.board(conn, hours=hours)
        sig = news_mod.signal_symbols(conn)   # cross-plane: which trending names ALSO show a smart-money signal
    for r in board:
        r["has_signal"] = r.get("symbol") in sig
    return {"sources": sentiment.sources_status(), "hours": hours, "board": board,
            # Separate from `sources` on purpose. Those feed the attention BOARD (per-ticker volume
            # and mood). These are the networks the product reads for what consequential ACCOUNTS
            # are saying, which lands on the Radar as events rather than here as a ticker score.
            # The brief is explicit that this panel must name the networks it covers instead of
            # showing an unexplained "N/A" for X forever.
            "voices": [sources.gate(k) for k in ("bluesky", "x")],
            "note": None if board else ("No attention data yet — run `ingest-sentiment` (Wikipedia + "
                                        "Hacker News need no key), or connect Reddit for discussion sentiment.")}


@app.get("/api/sentiment/{symbol}")
def sentiment_endpoint(symbol: str) -> dict:
    with db.connect() as conn:
        d = social_mod.symbol_detail(conn, symbol)
    return {"found": d is not None, "symbol": symbol.upper(), "detail": d,
            "sources": sentiment.sources_status()}


# ------------------------------------------------------------------- community & social (Slice F)

@app.patch("/api/profile")
def profile_set(req: ProfileReq, response: Response, tos_session: str | None = Cookie(None)) -> dict:
    with db.connect() as conn:
        user = authn.session_user(conn, tos_session)
        if not user:
            response.status_code = 401
            return {"error": "log in to set your profile"}
        res = community.set_profile(conn, user["id"], handle=req.handle, bio=req.bio)
        if res.get("error"):
            response.status_code = 400
        return res


@app.get("/api/u/{handle}")
def user_profile(handle: str, tos_session: str | None = Cookie(None)) -> dict:
    with db.connect() as conn:
        viewer = authn.session_user(conn, tos_session)
        prof = community.public_profile(conn, handle.lower(), viewer["id"] if viewer else None)
        if prof.get("found"):
            with conn.cursor() as cur:
                cur.execute(sql.SQL("SELECT {cols} FROM trades WHERE user_id=%s AND is_public "
                                    "AND hidden=false ORDER BY created_at DESC LIMIT 100"
                                    ).format(cols=_TRADE_COL_SQL), (prof["id"],))
                prof["trades"] = [_trade_to_dict(r) for r in cur.fetchall()]
    return prof


def _community_open(conn, response: Response) -> bool:
    """Community-writes kill-switch (admin flag). Off -> the social surface goes read-only."""
    if not flags.enabled(conn, "community_writes"):
        response.status_code = 403
        return False
    return True


@app.post("/api/users/follow")
def user_follow(req: FollowUserReq, response: Response, tos_session: str | None = Cookie(None)) -> dict:
    with db.connect() as conn:
        user = authn.session_user(conn, tos_session)
        if not user:
            response.status_code = 401
            return {"error": "log in to follow traders"}
        if not _community_open(conn, response):
            return {"error": "community posting is temporarily disabled"}
        res = community.follow_user(conn, user["id"], req.handle.strip().lstrip("@").lower())
        if res.get("error"):
            response.status_code = 400
        return res


@app.delete("/api/users/follow/{handle}")
def user_unfollow(handle: str, response: Response, tos_session: str | None = Cookie(None)) -> dict:
    with db.connect() as conn:
        user = authn.session_user(conn, tos_session)
        if not user:
            response.status_code = 401
            return {"error": "not authenticated"}
        return community.unfollow_user(conn, user["id"], handle.strip().lstrip("@").lower())


@app.get("/api/community/feed")
def community_feed(scope: str = "public", before_id: int | None = None,
                   tos_session: str | None = Cookie(None)) -> dict:
    scope = scope if scope in ("public", "following") else "public"
    with db.connect() as conn:
        user = authn.session_user(conn, tos_session)
        feed = community.public_feed(conn, viewer_id=user["id"] if user else None, scope=scope, before_id=before_id)
    return {"scope": scope, "authenticated": bool(user), "feed": feed}


@app.post("/api/trades/{tid}/react")
def trade_react(tid: int, req: ReactReq, response: Response, tos_session: str | None = Cookie(None)) -> dict:
    with db.connect() as conn:
        user = authn.session_user(conn, tos_session)
        if not user:
            response.status_code = 401
            return {"error": "log in to react"}
        if not _community_open(conn, response):
            return {"error": "community posting is temporarily disabled"}
        res = community.react(conn, user["id"], tid, req.kind)
        if res.get("error"):
            response.status_code = 400
        return res


@app.delete("/api/trades/{tid}/react/{kind}")
def trade_unreact(tid: int, kind: str, response: Response, tos_session: str | None = Cookie(None)) -> dict:
    with db.connect() as conn:
        user = authn.session_user(conn, tos_session)
        if not user:
            response.status_code = 401
            return {"error": "not authenticated"}
        return community.unreact(conn, user["id"], tid, kind)


@app.get("/api/trades/{tid}/comments")
def trade_comments_list(tid: int, tos_session: str | None = Cookie(None)) -> dict:
    with db.connect() as conn:
        user = authn.session_user(conn, tos_session)
        return community.list_comments(conn, tid, user["id"] if user else None)


@app.post("/api/trades/{tid}/comments")
def trade_comment_add(tid: int, req: CommentReq, response: Response, tos_session: str | None = Cookie(None)) -> dict:
    if not _rate_ok(limit=10):
        response.status_code = 429
        return {"error": "slow down a moment and try again"}
    with db.connect() as conn:
        user = authn.session_user(conn, tos_session)
        if not user:
            response.status_code = 401
            return {"error": "log in to comment"}
        if not _community_open(conn, response):
            return {"error": "community posting is temporarily disabled"}
        res = community.add_comment(conn, user["id"], tid, req.body)
        if res.get("error"):
            response.status_code = 400
        return res


@app.delete("/api/comments/{cid}")
def comment_delete(cid: int, response: Response, tos_session: str | None = Cookie(None)) -> dict:
    with db.connect() as conn:
        user = authn.session_user(conn, tos_session)
        if not user:
            response.status_code = 401
            return {"error": "not authenticated"}
        res = community.delete_comment(conn, user["id"], cid, is_admin=user["tier"] == "admin")
        if res.get("error"):
            response.status_code = 403
        return res


@app.post("/api/report")
def content_report(req: ReportReq, response: Response, tos_session: str | None = Cookie(None)) -> dict:
    with db.connect() as conn:
        user = authn.session_user(conn, tos_session)
        if not user:
            response.status_code = 401
            return {"error": "log in to report"}
        if not _community_open(conn, response):
            return {"error": "community posting is temporarily disabled"}
        res = community.report(conn, user["id"], req.target_type, req.target_id, req.reason)
        if res.get("error"):
            response.status_code = 400
        return res


@app.get("/api/leaderboard/traders")
def leaderboard_traders() -> dict:
    with db.connect() as conn:
        board = community.trader_leaderboard_data(conn)
    return {"leaderboard": board, "min_closed": community.LEADERBOARD_MIN_CLOSED}


# ------------------------------------------------------------------ admin (Slice K)

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


@app.get("/api/admin/overview")
def admin_overview(response: Response, tos_session: str | None = Cookie(None)) -> dict:
    with db.connect() as conn:
        user = _require_admin(conn, tos_session, response)
        if not user:
            return {"error": "admin only"}
        return {"overview": admin.overview(conn), "flags": flags.all_states(conn),
                "config": _ops_config()}


@app.get("/api/admin/moderation")
def admin_moderation(response: Response, tos_session: str | None = Cookie(None)) -> dict:
    with db.connect() as conn:
        user = _require_admin(conn, tos_session, response)
        if not user:
            return {"error": "admin only"}
        return {"queue": admin.moderation_queue(conn), "reports_to_hide": community.REPORTS_TO_HIDE}


@app.post("/api/admin/moderation/resolve")
def admin_moderation_resolve(req: AdminResolveReq, response: Response,
                             tos_session: str | None = Cookie(None)) -> dict:
    with db.connect() as conn:
        user = _require_admin(conn, tos_session, response)
        if not user:
            return {"error": "admin only"}
        res = admin.resolve(conn, user, req.target_type, req.target_id, req.action)
        if res.get("error"):
            response.status_code = 400
        return res


@app.get("/api/admin/users")
def admin_users(q: str = "", response: Response = None, tos_session: str | None = Cookie(None)) -> dict:
    with db.connect() as conn:
        user = _require_admin(conn, tos_session, response)
        if not user:
            return {"error": "admin only"}
        return {"users": admin.list_users(conn, q), "tiers": list(admin.TIER_TARGETS)}


@app.post("/api/admin/users/{uid}/tier")
def admin_set_tier(uid: int, req: AdminTierReq, response: Response,
                   tos_session: str | None = Cookie(None)) -> dict:
    with db.connect() as conn:
        user = _require_admin(conn, tos_session, response)
        if not user:
            return {"error": "admin only"}
        res = admin.set_tier(conn, user, uid, req.tier)
        if res.get("error"):
            response.status_code = 400
        return res


@app.post("/api/admin/users/{uid}/ban")
def admin_ban(uid: int, req: AdminBanReq, response: Response,
              tos_session: str | None = Cookie(None)) -> dict:
    with db.connect() as conn:
        user = _require_admin(conn, tos_session, response)
        if not user:
            return {"error": "admin only"}
        res = admin.set_banned(conn, user, uid, req.banned)
        if res.get("error"):
            response.status_code = 400
        return res


@app.get("/api/admin/flags")
def admin_flags(response: Response, tos_session: str | None = Cookie(None)) -> dict:
    with db.connect() as conn:
        user = _require_admin(conn, tos_session, response)
        if not user:
            return {"error": "admin only"}
        return {"flags": flags.all_states(conn), "config": _ops_config()}


@app.post("/api/admin/flags/{name}")
def admin_set_flag(name: str, req: AdminFlagReq, response: Response,
                   tos_session: str | None = Cookie(None)) -> dict:
    with db.connect() as conn:
        user = _require_admin(conn, tos_session, response)
        if not user:
            return {"error": "admin only"}
        res = flags.set_flag(conn, name, req.enabled)
        if res.get("error"):
            response.status_code = 400
            return res
        authn.audit(conn, user["email"], "admin_set_flag", name, {"enabled": req.enabled})
        return res


@app.get("/api/admin/watchlist-accounts")
def admin_watchlist_accounts(response: Response, tos_session: str | None = Cookie(None)) -> dict:
    """The consequential-accounts watchlist. The brief requires this be first-class editable data
    with a management interface rather than a hardcoded array — this is that interface."""
    with db.connect() as conn:
        # _require_admin returns the USER on success and None on failure. Getting this backwards
        # served the list to anonymous callers.
        if not _require_admin(conn, tos_session, response):
            return {"error": "admin only"}
        return {"accounts": watchlist_accounts.listing(conn),
                "note": "`influence` is a stated editorial weight, not a measurement. It records "
                        "that this product treats a central bank's words as more consequential "
                        "than an anonymous account; it does not claim to have measured anyone."}


@app.post("/api/admin/watchlist-accounts")
def admin_watchlist_account_save(req: WatchlistAccountReq, response: Response,
                                 tos_session: str | None = Cookie(None)) -> dict:
    with db.connect() as conn:
        me = _require_admin(conn, tos_session, response)
        if not me:
            return {"error": "admin only"}
        out = watchlist_accounts.upsert(conn, req.model_dump())
        if "error" in out:
            response.status_code = 400
            return out
        conn.commit()
        authn.audit(conn, (me or {}).get("email"), "watchlist_account.save",
                    f"{req.platform}:{req.handle}", {"influence": req.influence})
        return out


@app.get("/api/admin/audit")
def admin_audit(action: str | None = None, limit: int = 100, response: Response = None,
                tos_session: str | None = Cookie(None)) -> dict:
    with db.connect() as conn:
        user = _require_admin(conn, tos_session, response)
        if not user:
            return {"error": "admin only"}
        return {"entries": admin.audit_tail(conn, limit=limit, action=action),
                "actions": admin.audit_actions(conn)}


def _ops_config() -> dict:
    """Real, READ-ONLY operational config the admin can see but not toggle from the web: it is
    controlled by deployment env / third-party keys, so we show its true state instead of a fake
    switch (same honesty rule as the 'not connected yet' sources)."""
    from . import config
    return {
        "short_interest": {"enabled": config.short_interest_enabled(), "controlled_by": "ENABLE_SHORT_INTEREST (env)"},
        "reddit": {"enabled": config.reddit_configured(), "controlled_by": "REDDIT_CLIENT_ID/SECRET (env)"},
        "youtube": {"enabled": config.youtube_configured(), "controlled_by": "YOUTUBE_API_KEY (env)"},
        "stripe": {"enabled": billing.provider_configured(), "controlled_by": "STRIPE_SECRET_KEY (env)"},
    }


@app.get("/api/search")
def search_endpoint(q: str = "") -> dict:
    """Unified search across issuers, institutions, insiders, the library, and public traders
    (docs/threat-models — read-only; only public handles, never emails)."""
    with db.connect() as conn:
        results = search.search(conn, q)
    return {"query": q.strip()[:64], "total": sum(len(v) for v in results.values()), "results": results}


@app.get("/api/crypto/markets")
def crypto_markets(limit: int = 25) -> dict:
    """Real crypto market data from CoinGecko (docs/threat-models/crypto.md). Market data + risk
    labels, not advice; on any upstream failure returns an honest error, never a fabricated price."""
    limit = max(1, min(50, limit))
    with db.connect() as conn:
        if not flags.enabled(conn, "crypto"):
            return {"markets": [], "source": "CoinGecko", "disabled": True,
                    "error": "the crypto surface is currently disabled"}
    try:
        return {"markets": crypto.markets(limit), "source": "CoinGecko",
                "note": "Market data, not advice. Crypto is high-risk and volatile."}
    except Exception:
        log.warning("crypto markets fetch failed")
        return {"markets": [], "source": "CoinGecko", "error": "crypto data temporarily unavailable"}


@app.get("/api/crypto/structure")
def crypto_structure() -> dict:
    """Crypto market STRUCTURE — who is positioned, how crowded, and whether money is entering.

    The price table this replaces showed numbers anyone can get free in five seconds. Positioning
    is free too but almost nobody surfaces it, and it is what explains a move rather than
    restating it. Every reading carries the condition that would break it."""
    from .ingestion import derivatives
    try:
        deriv = derivatives.fetch_cached()
    except Exception as exc:
        log.warning("derivatives unavailable (%s)", type(exc).__name__)
        return {"available": False,
                "note": "Positioning data is temporarily unavailable from the exchange."}
    stables = []
    try:
        stables = [c for c in crypto.markets(limit=60) if c.get("symbol", "").upper()
                   in ("USDT", "USDC", "DAI", "USDS", "PYUSD")]
    except Exception as exc:
        log.warning("stablecoin supply unavailable (%s)", type(exc).__name__)

    with db.connect() as conn, conn.cursor() as cur:
        # Narrative, from our own store: what has this product actually interpreted about crypto?
        cur.execute("""SELECT c.id, c.mechanism, c.confidence, c.horizon, e.title, e.source_url
                         FROM claims c LEFT JOIN events e ON e.id = c.event_id
                        WHERE c.created_at >= now() - interval '14 days'
                          AND (e.category = 'protocol_upgrade'
                               OR EXISTS (SELECT 1 FROM jsonb_array_elements(c.affected) a
                                           WHERE upper(a->>'value') IN
                                             ('BTC','ETH','BITCOIN','ETHEREUM','CRYPTO','SOL')))
                     ORDER BY c.confidence DESC LIMIT 5""")
        ncols = ("id", "mechanism", "confidence", "horizon", "headline", "url")
        narrative = [dict(zip(ncols, r, strict=True)) for r in cur.fetchall()]

    out = crypto_intel.compose(deriv["positioning"], stables, narrative)
    return {"available": True, **out, "failed_symbols": deriv["failed"],
            "source": deriv["source"]}


@app.get("/api/crypto/trending")
def crypto_trending() -> dict:
    with db.connect() as conn:
        if not flags.enabled(conn, "crypto"):
            return {"trending": [], "source": "CoinGecko", "disabled": True}
    try:
        return {"trending": crypto.trending(), "source": "CoinGecko"}
    except Exception:
        log.warning("crypto trending fetch failed")
        return {"trending": [], "source": "CoinGecko", "error": "unavailable"}


def _watch_conviction(sm, att):
    """A transparent 0-100 conviction blend of the two REAL per-name scores we have — smart-money
    conviction and public attention. It is NOT a technical/fundamental/momentum rating: we don't
    compute those and never fake them, so the watchlist shows only what's real."""
    if sm and sm.get("score") is not None:
        score = sm["score"]
        if att and att.get("score"):
            score = round(0.75 * score + 0.25 * att["score"])
        return {"score": int(score), "basis": "smart-money" + (" + attention" if att and att.get("score") else "")}
    if att and att.get("score"):
        return {"score": int(round(att["score"] * 0.55)), "basis": "attention only"}
    return None


@app.get("/api/watchlist")
def watchlist_get(tos_session: str | None = Cookie(None)) -> dict:
    """Each watched name enriched with the REAL per-ticker scores: smart-money conviction (from the
    convergence cluster), public attention (social), the latest impactful news, the next earnings date,
    and a transparent conviction blend of the two. No fabricated technical/fundamental scores.

    Scoped to the session (bug B-22). This used to take the owner as a QUERY PARAMETER defaulting
    to 'demo', so every account shared one list and any caller could read another's by changing a
    parameter."""
    with db.connect() as conn, conn.cursor() as cur:
        user = authn.session_user(conn, tos_session)
        if not user:
            return {"authenticated": False, "watchlist": []}
        cur.execute("SELECT symbol FROM watchlists WHERE user_id=%s ORDER BY created_at", (user["id"],))
        symbols = [r[0] for r in cur.fetchall()]
        nextev: dict = {}   # soonest upcoming earnings per symbol, one pass over the calendar
        for e in events_mod.upcoming(conn, days=30):
            if e.get("scope") == "company" and e.get("symbol") and e["symbol"] not in nextev:
                nextev[e["symbol"]] = {"date": e["date"], "kind": e.get("kind"), "title": e.get("title")}
        rows = []
        for sym in symbols:
            ent = _resolve_symbol(cur, sym)
            item = {"symbol": sym, "resolved": ent is not None}
            sm = att = None
            if ent:
                eid = ent[0]
                item["name"] = ent[2]
                cur.execute(
                    """SELECT c.score, c.confidence_bucket FROM signal_clusters c
                       WHERE c.issuer_entity=%s AND c.as_of=(SELECT max(as_of) FROM signal_clusters)""",
                    (eid,),
                )
                cl = cur.fetchone()
                item["cluster"] = {"score": float(cl[0]), "bucket": cl[1]} if cl else None
                if cl:
                    sm = {"score": presentation.smart_money_score(float(cl[0])), "bucket": cl[1]}
            sdata = sentiment.symbol_sentiment(conn, sym)
            if sdata:
                att = {"score": sdata["attention"], "velocity": sdata["velocity"], "sentiment": sdata["sentiment"]}
            nz = news_mod.ranked_news(conn, symbol=sym, hours=240, limit=1)
            item["smart_money"] = sm
            item["attention"] = att
            item["news"] = {"headline": nz[0]["headline"], "impact": nz[0]["impact"], "url": nz[0]["url"]} if nz else None
            item["next_event"] = nextev.get(sym)
            item["conviction"] = _watch_conviction(sm, att)
            rows.append(item)
    return {"authenticated": True, "watchlist": rows}


@app.post("/api/watchlist/{symbol}")
def watchlist_add(symbol: str, response: Response, tos_session: str | None = Cookie(None)) -> dict:
    sym = symbol.strip().upper()
    if not sym or len(sym) > 12 or not re.fullmatch(r"[A-Z0-9.\-]+", sym):
        response.status_code = 400
        return {"error": "not a valid symbol"}
    with db.connect() as conn, conn.cursor() as cur:
        user = authn.session_user(conn, tos_session)
        if not user:
            response.status_code = 401
            return {"error": "log in to keep a watchlist"}
        cur.execute(
            "INSERT INTO watchlists (user_id, symbol) VALUES (%s,%s) "
            "ON CONFLICT (user_id, symbol) DO NOTHING", (user["id"], sym))
        conn.commit()
    return {"symbol": sym, "added": True}


@app.delete("/api/watchlist/{symbol}")
def watchlist_remove(symbol: str, response: Response, tos_session: str | None = Cookie(None)) -> dict:
    with db.connect() as conn, conn.cursor() as cur:
        user = authn.session_user(conn, tos_session)
        if not user:
            response.status_code = 401
            return {"error": "log in to keep a watchlist"}
        cur.execute("DELETE FROM watchlists WHERE user_id=%s AND symbol=%s",
                    (user["id"], symbol.strip().upper()))
        conn.commit()
    return {"symbol": symbol.strip().upper(), "removed": True}


# ------------------------------------------------------------ follows / alerts (Slice B)
# All per-user surfaces enforce object-level authorization: every read and write is scoped to the
# session's user_id, so no id in the URL or body can reach another account's follows or alerts.

@app.get("/api/follows")
def follows_list(tos_session: str | None = Cookie(None)) -> dict:
    with db.connect() as conn, conn.cursor() as cur:
        user = authn.session_user(conn, tos_session)
        if not user:
            return {"authenticated": False, "follows": []}
        cur.execute("SELECT id, kind, ref, label, created_at FROM follows WHERE user_id=%s ORDER BY created_at DESC",
                    (user["id"],))
        follows = [{"id": i, "kind": k, "ref": ref, "label": label, "created_at": ca.isoformat()}
                   for i, k, ref, label, ca in cur.fetchall()]
    return {"authenticated": True, "follows": follows}


@app.post("/api/follows")
def follows_add(req: FollowReq, response: Response, tos_session: str | None = Cookie(None)) -> dict:
    if req.kind not in ("symbol", "insider", "filer"):
        response.status_code = 400
        return {"error": "invalid follow kind"}
    ref = req.ref.strip()
    ref = ref.upper() if req.kind == "symbol" else ref
    with db.connect() as conn, conn.cursor() as cur:
        user = authn.session_user(conn, tos_session)
        if not user:
            response.status_code = 401
            return {"error": "log in to follow and get alerts"}
        max_follows = billing.entitlements(user["tier"])["max_follows"]
        cur.execute("SELECT count(*) FROM follows WHERE user_id=%s", (user["id"],))
        if cur.fetchone()[0] >= max_follows:
            response.status_code = 403
            return {"error": f"Your plan allows {max_follows} follows. Upgrade for more.", "upgrade": True}
        cur.execute(
            "INSERT INTO follows (user_id, kind, ref, label) VALUES (%s,%s,%s,%s) "
            "ON CONFLICT (user_id, kind, ref) DO NOTHING RETURNING id",
            (user["id"], req.kind, ref, (req.label or "").strip() or None),
        )
        row = cur.fetchone()
        conn.commit()
    return {"followed": True, "kind": req.kind, "ref": ref, "id": row[0] if row else None}


@app.delete("/api/follows/{follow_id}")
def follows_remove(follow_id: int, response: Response, tos_session: str | None = Cookie(None)) -> dict:
    with db.connect() as conn, conn.cursor() as cur:
        user = authn.session_user(conn, tos_session)
        if not user:
            response.status_code = 401
            return {"error": "not authenticated"}
        cur.execute("DELETE FROM follows WHERE id=%s AND user_id=%s", (follow_id, user["id"]))  # object-level check
        conn.commit()
        removed = cur.rowcount
    return {"removed": bool(removed)}


@app.get("/api/notifications")
def notifications_list(limit: int = 50, tos_session: str | None = Cookie(None)) -> dict:
    limit = max(1, min(100, limit))
    with db.connect() as conn, conn.cursor() as cur:
        user = authn.session_user(conn, tos_session)
        if not user:
            return {"authenticated": False, "unread": 0, "notifications": []}
        cur.execute(
            """SELECT id, kind, title, body, symbol, entity_id, created_at, read_at
               FROM notifications WHERE user_id=%s ORDER BY created_at DESC LIMIT %s""",
            (user["id"], limit),
        )
        items = [{"id": i, "kind": k, "title": t, "body": b, "symbol": s, "entity_id": e,
                  "created_at": ca.isoformat(), "read": ra is not None}
                 for i, k, t, b, s, e, ca, ra in cur.fetchall()]
        cur.execute("SELECT count(*) FROM notifications WHERE user_id=%s AND read_at IS NULL", (user["id"],))
        unread = cur.fetchone()[0]
    return {"authenticated": True, "unread": unread, "notifications": items}


@app.post("/api/notifications/read")
def notifications_read(response: Response, tos_session: str | None = Cookie(None)) -> dict:
    with db.connect() as conn, conn.cursor() as cur:
        user = authn.session_user(conn, tos_session)
        if not user:
            response.status_code = 401
            return {"error": "not authenticated"}
        cur.execute("UPDATE notifications SET read_at=now() WHERE user_id=%s AND read_at IS NULL", (user["id"],))
        conn.commit()
        marked = cur.rowcount
    return {"marked_read": marked}


@app.get("/api/alert-prefs")
def alert_prefs_get(tos_session: str | None = Cookie(None)) -> dict:
    from .alerts import DEFAULT_PREFS
    with db.connect() as conn, conn.cursor() as cur:
        user = authn.session_user(conn, tos_session)
        if not user:
            return {"authenticated": False, "prefs": dict(DEFAULT_PREFS)}
        cur.execute("SELECT new_high_conviction, followed_activity, min_score, email_enabled FROM alert_prefs WHERE user_id=%s",
                    (user["id"],))
        r = cur.fetchone()
        prefs = ({"new_high_conviction": r[0], "followed_activity": r[1], "min_score": r[2], "email_enabled": r[3]}
                 if r else dict(DEFAULT_PREFS))
    return {"authenticated": True, "prefs": prefs}


@app.put("/api/alert-prefs")
def alert_prefs_set(req: AlertPrefsReq, response: Response, tos_session: str | None = Cookie(None)) -> dict:
    ms = max(0, min(100, req.min_score))
    with db.connect() as conn, conn.cursor() as cur:
        user = authn.session_user(conn, tos_session)
        if not user:
            response.status_code = 401
            return {"error": "not authenticated"}
        cur.execute(
            """INSERT INTO alert_prefs (user_id, new_high_conviction, followed_activity, min_score, email_enabled, updated_at)
               VALUES (%s,%s,%s,%s,%s, now())
               ON CONFLICT (user_id) DO UPDATE SET new_high_conviction=EXCLUDED.new_high_conviction,
                   followed_activity=EXCLUDED.followed_activity, min_score=EXCLUDED.min_score,
                   email_enabled=EXCLUDED.email_enabled, updated_at=now()""",
            (user["id"], req.new_high_conviction, req.followed_activity, ms, req.email_enabled),
        )
        conn.commit()
    return {"saved": True, "prefs": {"new_high_conviction": req.new_high_conviction,
            "followed_activity": req.followed_activity, "min_score": ms, "email_enabled": req.email_enabled}}


# ------------------------------------------------------------ paper portfolios (Slice C)

def _default_opened_on(cur, symbol: str, entity_id: int | None):
    """Entry for a paper position: the name's first convergence date if it has one (shadow from
    the signal), else ~90 days before its latest price so there is a real window, else today."""
    if entity_id is not None:
        cur.execute("SELECT min(as_of)::date FROM signal_clusters WHERE issuer_entity=%s", (entity_id,))
        r = cur.fetchone()
        if r and r[0]:
            return r[0]
    cur.execute("SELECT max(day) FROM prices_eod WHERE symbol=%s", (symbol,))
    r = cur.fetchone()
    if r and r[0]:
        return r[0] - timedelta(days=90)
    return datetime.now(UTC).date()


@app.post("/api/portfolios")
def portfolio_create(req: PortfolioReq, response: Response, tos_session: str | None = Cookie(None)) -> dict:
    kind = req.kind if req.kind in ("manual", "shadow_bucket") else "manual"
    buckets = [b for b in (req.buckets or ["high", "medium"]) if b in ("low", "medium", "high")] or ["high", "medium"]
    with db.connect() as conn, conn.cursor() as cur:
        user = authn.session_user(conn, tos_session)
        if not user:
            response.status_code = 401
            return {"error": "log in to build a portfolio"}
        max_p = billing.entitlements(user["tier"])["max_portfolios"]
        cur.execute("SELECT count(*) FROM portfolios WHERE user_id=%s", (user["id"],))
        if cur.fetchone()[0] >= max_p:
            response.status_code = 403
            return {"error": f"Your plan allows {max_p} portfolio(s). Upgrade for more.", "upgrade": True}
        spec = {"buckets": buckets} if kind == "shadow_bucket" else {}
        cur.execute("INSERT INTO portfolios (user_id, name, kind, spec) VALUES (%s,%s,%s,%s) RETURNING id",
                    (user["id"], (req.name.strip()[:80] or "Portfolio"), kind, Json(spec)))
        pid = cur.fetchone()[0]
        conn.commit()
    added = 0
    if kind == "shadow_bucket":
        with db.connect() as conn:
            added = portfolio.populate_shadow(conn, pid, buckets)
    return {"created": True, "id": pid, "kind": kind, "positions_added": added}


@app.get("/api/portfolios")
def portfolios_list(tos_session: str | None = Cookie(None)) -> dict:
    with db.connect() as conn:
        user = authn.session_user(conn, tos_session)
        if not user:
            return {"authenticated": False, "portfolios": []}
        return {"authenticated": True, "portfolios": portfolio.list_for_user(conn, user["id"])}


@app.get("/api/portfolios/{pid}")
def portfolio_get(pid: int, tos_session: str | None = Cookie(None)) -> dict:
    with db.connect() as conn:
        user = authn.session_user(conn, tos_session)
        if not user:
            return {"found": False, "authenticated": False}
        return portfolio.detail(conn, pid, user["id"])  # scoped to user_id inside


@app.post("/api/portfolios/{pid}/positions")
def portfolio_add_position(pid: int, req: PositionReq, response: Response, tos_session: str | None = Cookie(None)) -> dict:
    sym = req.symbol.strip().upper()
    with db.connect() as conn, conn.cursor() as cur:
        user = authn.session_user(conn, tos_session)
        if not user:
            response.status_code = 401
            return {"error": "not authenticated"}
        cur.execute("SELECT 1 FROM portfolios WHERE id=%s AND user_id=%s", (pid, user["id"]))
        if not cur.fetchone():
            response.status_code = 404
            return {"error": "portfolio not found"}
        ent = _resolve_symbol(cur, sym)
        entity_id = ent[0] if ent else None
        if req.opened_on:
            try:
                opened = date.fromisoformat(req.opened_on)
            except ValueError:
                response.status_code = 400
                return {"error": "opened_on must be YYYY-MM-DD"}
        else:
            opened = _default_opened_on(cur, sym, entity_id)
        cur.execute("INSERT INTO portfolio_positions (portfolio_id, symbol, entity_id, opened_on) "
                    "VALUES (%s,%s,%s,%s) ON CONFLICT (portfolio_id, symbol) DO NOTHING RETURNING id",
                    (pid, sym, entity_id, opened))
        row = cur.fetchone()
        conn.commit()
    return {"added": bool(row), "symbol": sym, "opened_on": opened.isoformat()}


@app.delete("/api/portfolios/{pid}")
def portfolio_delete(pid: int, response: Response, tos_session: str | None = Cookie(None)) -> dict:
    with db.connect() as conn, conn.cursor() as cur:
        user = authn.session_user(conn, tos_session)
        if not user:
            response.status_code = 401
            return {"error": "not authenticated"}
        cur.execute("DELETE FROM portfolios WHERE id=%s AND user_id=%s", (pid, user["id"]))
        conn.commit()
        return {"removed": bool(cur.rowcount)}


@app.delete("/api/portfolios/{pid}/positions/{pos_id}")
def portfolio_remove_position(pid: int, pos_id: int, response: Response, tos_session: str | None = Cookie(None)) -> dict:
    with db.connect() as conn, conn.cursor() as cur:
        user = authn.session_user(conn, tos_session)
        if not user:
            response.status_code = 401
            return {"error": "not authenticated"}
        cur.execute("DELETE FROM portfolio_positions p USING portfolios pf "
                    "WHERE p.id=%s AND p.portfolio_id=pf.id AND pf.id=%s AND pf.user_id=%s",
                    (pos_id, pid, user["id"]))
        conn.commit()
        return {"removed": bool(cur.rowcount)}


@app.get("/api/track-record")
def track_record() -> dict:
    """Live public track record: the realized excess return vs SPY of shadowing each convergence
    bucket, straight from the backtest. Published even when unflattering — calibration is the brand."""
    from .backtest.run import compute_calibration
    with db.connect() as conn:
        cal = compute_calibration(conn)
    return {"per_bucket": cal["per_bucket"], "horizons": cal.get("horizons", [30, 90, 180]),
            "episodes_total": cal.get("episodes_total"),
            "note": "The realized excess return vs SPY of shadowing each convergence bucket, updated as "
                    "episodes resolve. Buckets under 30 resolved episodes read 'insufficient sample'. We "
                    "publish this even when it is unflattering. Nothing here is advice or a promise of future results."}


# ------------------------------------------------------------ billing + Pro API (Slice D)

@app.get("/api/billing/plans")
def billing_plans(tos_session: str | None = Cookie(None)) -> dict:
    with db.connect() as conn:
        user = authn.session_user(conn, tos_session)
        sub = billing.current_subscription(conn, user["id"]) if user else {"plan": "free", "status": "active"}
    plans = [{"id": k, "name": v["name"], "price": v["price"], "tier": v["tier"],
              "blurb": v.get("blurb"),
              "entitlements": billing.ENTITLEMENTS[v["tier"]]} for k, v in billing.PLANS.items()]
    return {"plans": plans, "current": sub, "provider_configured": billing.provider_configured(),
            "authenticated": bool(user)}


@app.post("/api/billing/checkout")
def billing_checkout(req: CheckoutReq, request: Request, response: Response, tos_session: str | None = Cookie(None)) -> dict:
    with db.connect() as conn:
        user = authn.session_user(conn, tos_session)
        if not user:
            response.status_code = 401
            return {"error": "log in to upgrade"}
        out = billing.create_checkout(conn, user, req.plan, str(request.base_url).rstrip("/"))
    if out.get("error"):
        response.status_code = 400
    return out


@app.post("/api/billing/test-activate")
def billing_test_activate(req: CheckoutReq, response: Response, tos_session: str | None = Cookie(None)) -> dict:
    with db.connect() as conn:
        user = authn.session_user(conn, tos_session)
        if not user:
            response.status_code = 401
            return {"error": "not authenticated"}
        out = billing.test_activate(conn, user, req.plan)
    if out.get("error"):
        response.status_code = 403
    return out


@app.post("/api/billing/cancel")
def billing_cancel(response: Response, tos_session: str | None = Cookie(None)) -> dict:
    with db.connect() as conn:
        user = authn.session_user(conn, tos_session)
        if not user:
            response.status_code = 401
            return {"error": "not authenticated"}
        return billing.cancel(conn, user)


@app.post("/api/billing/webhook")
async def billing_webhook(request: Request) -> JSONResponse:
    body = await request.body()
    with db.connect() as conn:
        out = billing.handle_webhook(conn, body, request.headers.get("stripe-signature"))
    return JSONResponse(out, status_code=200 if out.get("ok") else 400)


@app.post("/api/keys")
def keys_create(req: ApiKeyReq, response: Response, tos_session: str | None = Cookie(None)) -> dict:
    with db.connect() as conn:
        user = authn.session_user(conn, tos_session)
        if not user:
            response.status_code = 401
            return {"error": "not authenticated"}
        if not billing.entitlements(user["tier"])["api"]:
            response.status_code = 403
            return {"error": "API access requires the Pro plan", "upgrade": True}
        out = apikeys.generate(conn, user["id"], req.name)
        authn.audit(conn, user["email"], "api_key_create", out["prefix"])
    return out


@app.get("/api/keys")
def keys_list(tos_session: str | None = Cookie(None)) -> dict:
    with db.connect() as conn:
        user = authn.session_user(conn, tos_session)
        if not user:
            return {"authenticated": False, "api_enabled": False, "keys": []}
        return {"authenticated": True, "api_enabled": billing.entitlements(user["tier"])["api"],
                "keys": apikeys.list_keys(conn, user["id"])}


@app.delete("/api/keys/{key_id}")
def keys_revoke(key_id: int, response: Response, tos_session: str | None = Cookie(None)) -> dict:
    with db.connect() as conn:
        user = authn.session_user(conn, tos_session)
        if not user:
            response.status_code = 401
            return {"error": "not authenticated"}
        return {"revoked": apikeys.revoke(conn, user["id"], key_id)}


@app.get("/api/v1/clusters")
def v1_clusters(request: Request, min_confidence: str = "medium", limit: int = 50) -> JSONResponse:
    """The Pro data API. Authenticated by a scoped, hashed API key (Bearer). Every response carries
    a per-key `meta.trace` canary so a resold dataset is traceable to the leaking key."""
    auth = request.headers.get("authorization", "")
    raw = auth[7:].strip() if auth[:7].lower() == "bearer " else None
    min_rank = _BUCKET_RANK.get(min_confidence, 1)
    limit = max(1, min(200, limit))
    with db.connect() as conn:
        key = apikeys.verify(conn, raw)
        if not key:
            return JSONResponse({"error": "invalid or missing API key"}, status_code=401)
        if key["tier"] not in ("pro", "admin"):
            return JSONResponse({"error": "API access requires the Pro plan"}, status_code=403)
        if not apikeys.rate_ok(key["id"]):
            return JSONResponse({"error": "rate limit exceeded"}, status_code=429)
        rows: list[dict] = []
        with conn.cursor() as cur:
            aso = _effective_as_of(cur, "latest", key["tier"])
            if aso is not None:
                cur.execute(
                    """SELECT c.issuer_entity, e.name, c.score, c.confidence_bucket, c.voices, c.source_classes,
                              (SELECT symbol FROM security_map m WHERE m.entity_id=c.issuer_entity
                                 AND m.source='sec_company_tickers' ORDER BY confidence DESC LIMIT 1)
                       FROM signal_clusters c JOIN entities e ON e.id=c.issuer_entity
                       WHERE c.as_of=%s ORDER BY c.score DESC""",
                    (aso,),
                )
                for _ent, name, score, bucket, voices, classes, sym in cur.fetchall():
                    if _BUCKET_RANK[bucket] < min_rank:
                        continue
                    rows.append({"symbol": sym, "name": name,
                                 "smart_money_score": presentation.smart_money_score(float(score)),
                                 "score": float(score), "confidence_bucket": bucket,
                                 "voices": voices, "source_classes": classes})
                    if len(rows) >= limit:
                        break
        trace = apikeys.canary_trace(key["canary"], date.today().isoformat())
    return JSONResponse({"as_of": aso.isoformat() if aso else None, "count": len(rows), "clusters": rows,
                         "meta": {"trace": trace, "plan": key["tier"],
                                  "terms": "Licensed to your account. Redistribution is traceable via meta.trace."}})


@app.get("/api/library")
def library() -> dict:
    with db.connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT slug, kind, title, linked_source_classes, review_status FROM library_entries ORDER BY kind, title"
        )
        entries = [{"slug": s, "kind": k, "title": t, "linked_source_classes": lc, "review_status": rs}
                   for s, k, t, lc, rs in cur.fetchall()]
    return {"entries": entries,
            "note": "Educational library. Entries are original drafts pending founder review; every "
                    "factual claim traces to a listed public source. Nothing here is investment advice."}


@app.get("/api/library/{slug}")
def library_entry(slug: str) -> dict:
    with db.connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT slug, kind, title, body_md, sources, linked_source_classes, review_status FROM library_entries WHERE slug=%s",
            (slug,),
        )
        r = cur.fetchone()
    if r is None:
        return {"found": False, "slug": slug}
    return {"found": True, "slug": r[0], "kind": r[1], "title": r[2], "body_md": r[3],
            "sources": r[4], "linked_source_classes": r[5], "review_status": r[6]}


# --------------------------------------------------------------- shareable cards (Slice C)

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

def _card_data(cur, symbol: str) -> dict | None:
    ent = _resolve_symbol(cur, symbol)
    if ent is None:
        return None
    eid, _cik, name = ent
    aso = _effective_as_of(cur, "latest", "free")  # a public card uses the free (delayed) view
    r = None
    if aso is not None:
        cur.execute("SELECT score, confidence_bucket, inputs FROM signal_clusters WHERE issuer_entity=%s AND as_of=%s",
                    (eid, aso))
        r = cur.fetchone()
    if not r:
        return {"symbol": symbol, "name": name, "score": None, "bucket": None,
                "headline": "No active convergence right now"}
    score, bucket, inputs = r
    contribs = (inputs or {}).get("contributions", [])
    story = presentation.cluster_story(contribs, _voice_names(cur, [contribs]))
    return {"symbol": symbol, "name": name, "score": presentation.smart_money_score(float(score)),
            "bucket": bucket, "headline": story["headline"]}


@app.get("/api/card/{symbol}.svg")
def card_svg(symbol: str) -> Response:
    sym = symbol.strip().upper()
    with db.connect() as conn, conn.cursor() as cur:
        d = _card_data(cur, sym) or {"symbol": sym, "name": "", "score": None, "bucket": None,
                                     "headline": "Not a resolved issuer"}
    svg = presentation.score_card_svg(d["symbol"], d["name"], d["score"], d["bucket"], d["headline"],
                                      brand=config.brand_name())
    return Response(content=svg, media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=300"})


@app.get("/s/{symbol}", response_class=HTMLResponse)
def share_page(symbol: str) -> str:
    sym = symbol.strip().upper()
    with db.connect() as conn, conn.cursor() as cur:
        d = _card_data(cur, sym) or {"symbol": sym, "name": "", "score": None, "headline": "Not a resolved issuer"}
    e = presentation._xml_escape
    brand = config.brand_name()
    title = f"{sym} · Smart Money Score {d['score']}" if d.get("score") is not None else f"{sym} · {brand}"
    card = f"/api/card/{sym}.svg"
    # This page's card is still SVG -- it belongs to the convergence plane, which is being retired,
    # so it gets the absolute URLs and the tag block and no new renderer. The tags are what was
    # broken; a PNG here would be work on a surface scheduled for deletion.
    tags = _og_tags(title=title, description=d.get("headline") or "",
                    path=f"/s/{sym}", image_path=card, image_type="image/svg+xml")
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>{e(title)}</title>
{tags}
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>body{{background:#090b11;color:#d7e0ee;font-family:-apple-system,BlinkMacSystemFont,sans-serif;display:flex;flex-direction:column;align-items:center;gap:22px;padding:44px 16px}}img{{max-width:100%;width:640px;border-radius:16px;border:1px solid #222b3a}}a{{color:#5b8cff;text-decoration:none;font-weight:600;font-size:18px}}p{{color:#7a8699;font-size:13px;max-width:560px;text-align:center;line-height:1.5}}</style>
</head><body>
<img src="{card}" alt="{e(title)}">
<a href="/asset?symbol={e(sym)}">Open {e(sym)} on {e(brand)} &#8594;</a>
<p>{e(brand)} shows what the smartest money is quietly doing, with backtested, probability-framed context. Not investment advice.</p>
</body></html>'''


# ------------------------------------------------------------------- RECEIPTS
#
# The public, permanent, chained record of market calls. Read `tradeos/receipts/` for the reasoning;
# these are thin handlers over it, which is deliberate — none of the integrity logic lives in a
# route, so none of it can be bypassed by adding a second route later.
#
# Note which of these are PUBLIC. A record page, the board, the methodology, chain verification and
# the share card are readable by a stranger with no session, because the whole product argument is
# that a reader can check a caller without taking anything on trust, including an account with us.


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
        return receipts_calls.preview(symbol, horizon_days, conn)


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
                "disclaimer": RECEIPTS_DISCLAIMER}


@app.get("/api/receipts/methodology")
def receipts_methodology() -> dict:
    """The scoring rules as structured data, so no surface ever hardcodes them and drifts."""
    with db.connect() as conn:
        return {**receipts_record.methodology(),
                "universe": receipts_record.scoreable_universe(conn),
                "disclaimer": RECEIPTS_DISCLAIMER}


@app.get("/api/receipts/{handle}")
def receipts_for(handle: str, response: Response) -> dict:
    """One caller's whole record. Public, and misses come first."""
    with db.connect() as conn:
        caller = receipts_record.caller(handle, conn)
        if not caller:
            response.status_code = 404
            return {"error": "no such record."}
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


@app.get("/r/{handle}", response_class=HTMLResponse)
def receipt_share_page(handle: str) -> str:
    """Server rendered share page with OG tags, same pattern as /s/{symbol}.

    A link to a record has to render something in a feed. This page is that preview and a real
    entry point; the app's own record surface is behind the same URL for anyone with the bundle.
    """
    with db.connect() as conn:
        caller = receipts_record.caller(handle, conn)
        summary = receipts_record.summary(caller["id"], conn) if caller else None
    # From `receipts.card`, not `presentation`. The escape is one line and duplicating it is the
    # smaller cost: `presentation` imports `signals.convergence`, so borrowing a helper from it
    # would leave the Receipts share page holding the dead plane open. The duplicate disappears
    # when `presentation` does.
    e = receipts_card._xml_escape
    brand = config.brand_name()
    if not caller:
        return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
                f'<title>No such record · {e(brand)}</title>'
                f'<meta name="viewport" content="width=device-width, initial-scale=1"></head>'
                f'<body style="background:#05060c;color:#eaecf4;font-family:system-ui;padding:48px">'
                f'<h1>No record here</h1><p>Nobody holds the handle {e(handle)}.</p>'
                f'<p><a style="color:#6e8cff" href="/board">See every record</a></p></body></html>')

    counts = summary["counts"]
    if summary["gated"]:
        line = (f'{counts["hit"]} hit, {counts["miss"]} miss, {counts["inconclusive"]} inconclusive. '
                f'A rate is not shown below {receipts_record.SAMPLE_GATE} resolved calls.')
    else:
        line = (f'{summary["hit_rate"]:.1%} right on {summary["resolved_scoreable"]} resolved calls, '
                f'measured against SPY.')
    title = f'{caller["display_name"]} · the record · {brand}'
    # Escaped like everything else here. The handle regex makes a quote impossible to store today,
    # but that regex lives three hundred lines away in a different function, and a second way to
    # create a caller would break this silently.
    # PNG in the tags, SVG in the page body: the tags are read by scrapers that will not render
    # SVG, and the body is read by a browser that renders it sharper than any raster.
    png = f"/api/card/receipt/{caller['handle']}.png"
    card = e(f"/api/card/receipt/{caller['handle']}.svg")
    tags = _og_tags(title=title, description=line, path=f"/r/{caller['handle']}", image_path=png)
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>{e(title)}</title>
{tags}
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>body{{background:#05060c;color:#eaecf4;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;display:flex;flex-direction:column;align-items:center;gap:22px;padding:44px 16px}}img{{max-width:100%;width:660px;border-radius:16px;border:1px solid #1b2130}}a{{color:#6e8cff;text-decoration:none;font-weight:600;font-size:18px}}p{{color:#8b93ab;font-size:13px;max-width:600px;text-align:center;line-height:1.6}}</style>
</head><body>
<img src="{card}" alt="{e(title)}">
<a href="/record?handle={e(caller['handle'])}">Open the full record on {e(brand)} &#8594;</a>
<p>{e(line)}</p>
<p>{e(caller['identity_note'])}</p>
<p>{e(RECEIPTS_DISCLAIMER)}</p>
</body></html>'''


# ------------------------------------------------------------------- marketing site (Phase 7)
#
# Mounted BEFORE the app's own "/" mount, because that one is a catch-all: anything registered
# after it is unreachable. Two separate bundles on one origin, which is what makes both verifiable
# locally; Phase 8 puts the site on the apex domain and the app on a subdomain, the split the brief
# implies by calling it "a separate public application".
#
# Built from `site/`, which is gitignored like `frontend/dist` — absent in a checkout until
# `npm --prefix site run build`, so the mount is conditional rather than a hard dependency.

_SITE_DIR = Path(__file__).parent / "site_static"
if (_SITE_DIR / "index.html").exists():
    app.mount("/site", StaticFiles(directory=str(_SITE_DIR), html=True), name="marketing")


# ------------------------------------------------------------------- frontend (SPA)

_STATIC_DIR = Path(__file__).parent / "static"

# The front door. A signed-out visitor arriving at "/" is a STRANGER, and the thing built to explain
# this product to a stranger is the marketing site — so send them there rather than to the app's own
# landing screen, which still pitched the pre-rebrand product and which nothing else links to.
#
# The test is "is there a session cookie", not "is the session valid": deciding a redirect does not
# need a database round trip, and the only case it gets wrong — an expired cookie — lands on the app,
# which asks the reader to sign in. That is the right destination for an expired session anyway.
# Authorization is unaffected; every API route still checks the session itself.
#
# Registered BEFORE the "/" mount below, because that mount is a catch-all and swallows anything
# registered after it.
if (_SITE_DIR / "index.html").exists() and (_STATIC_DIR / "index.html").exists():
    @app.get("/", include_in_schema=False)
    def root(request: Request):
        if request.cookies.get(SESSION_COOKIE):
            return FileResponse(_STATIC_DIR / "index.html")
        return RedirectResponse("/site/", status_code=307)

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
