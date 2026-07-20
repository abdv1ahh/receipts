"""TradeOS API.

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
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Cookie, FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import authn, db

SESSION_COOKIE = "tos_session"
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "false").lower() == "true"  # true behind TLS in prod


class RegisterReq(BaseModel):
    email: str
    password: str
    invite_code: str


class LoginReq(BaseModel):
    email: str
    password: str
    totp_code: str | None = None


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

app = FastAPI(title="TradeOS", docs_url=None, redoc_url=None, openapi_url=None)

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


_CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; "
        "form-action 'self'")


@app.middleware("http")
async def harden(request: Request, call_next):
    # CSRF: refuse a cross-origin state-changing request (belt-and-braces with SameSite=Lax)
    if request.method in ("POST", "PUT", "DELETE", "PATCH"):
        origin = request.headers.get("origin")
        if origin:
            from urllib.parse import urlparse
            if urlparse(origin).netloc != request.headers.get("host"):
                return JSONResponse({"error": "cross-origin request refused"}, status_code=403)
    try:
        response = await call_next(request)
    except Exception:  # uniform error shape, never a stack trace to the client
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse({"error": "internal error"}, status_code=500)
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
            token, user = authn.register(conn, req.email, req.password, req.invite_code,
                                         ip=request.client.host if request.client else None,
                                         ua=request.headers.get("user-agent"))
    except authn.AuthError as exc:
        response.status_code = 400
        return {"error": str(exc)}
    _set_session_cookie(response, token)
    return {"user": user}


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
    now = datetime.now(timezone.utc)
    return {
        "event_time": event_time.isoformat(),
        "knowable_time": knowable_time.isoformat(),
        "staleness_days": (now.date() - event_time).days,
        "knowable_lag_days": (knowable_time.date() - event_time).days,
    }


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
                "score": float(score), "confidence_bucket": bucket,
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
    return {
        "found": True, "cluster_id": cid, "issuer_entity": issuer_id, "symbol": _symbol_for(cur, issuer_id),
        "name": name, "cik": cik, "as_of": aso2.isoformat(), "score": float(score),
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


@app.get("/api/watchlist")
def watchlist_get(user: str = "demo") -> dict:
    with db.connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT symbol FROM watchlists WHERE user_key=%s ORDER BY created_at", (user,))
        symbols = [r[0] for r in cur.fetchall()]
        rows = []
        for sym in symbols:
            ent = _resolve_symbol(cur, sym)
            item = {"symbol": sym, "resolved": ent is not None}
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
            rows.append(item)
    return {"user": user, "watchlist": rows}


@app.post("/api/watchlist/{symbol}")
def watchlist_add(symbol: str, user: str = "demo") -> dict:
    sym = symbol.strip().upper()
    with db.connect() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO watchlists (user_key, symbol) VALUES (%s,%s) ON CONFLICT (user_key, symbol) DO NOTHING",
            (user, sym),
        )
        conn.commit()
    return {"user": user, "symbol": sym, "added": True}


@app.delete("/api/watchlist/{symbol}")
def watchlist_remove(symbol: str, user: str = "demo") -> dict:
    with db.connect() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM watchlists WHERE user_key=%s AND symbol=%s", (user, symbol.strip().upper()))
        conn.commit()
    return {"user": user, "symbol": symbol.strip().upper(), "removed": True}


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


# ------------------------------------------------------------------- frontend (SPA)

_STATIC_DIR = Path(__file__).parent / "static"
if (_STATIC_DIR / "index.html").exists():
    app.mount("/", StaticFiles(directory=str(_STATIC_DIR), html=True), name="spa")
else:
    @app.get("/", response_class=HTMLResponse)
    def _no_build() -> str:
        return ("<h1>TradeOS API</h1><p>The dashboard bundle is not built. Run the multi-stage "
                "Docker build, or <code>cd frontend && npm install && npm run build</code>. "
                "API is live at <code>/api/clusters</code>, <code>/api/feeds</code>, "
                "<code>/api/definitions</code>.</p>")
