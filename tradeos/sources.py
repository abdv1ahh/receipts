"""The one place that knows every external source: what it is, what it powers, whether it is
connected, where its free key comes from, and how it is actually behaving right now.

Two things depend on this and nothing else should hardcode a source again:

  * the integration status page — the owner should never have to guess why a panel is empty;
  * the degradation gate the UI renders in place of a dead panel, which explains what the source
    would add and links straight to where the free key is obtained.

The rule this file exists to enforce: a missing source is a visible, explained gap with a next
step, never a wall and never a fabricated number. `state` is one of

  connected     working, or at least configured and expected to work
  needs_key     it would work, the operator just has to add a free key (`signup_url` says where)
  unavailable   no free path exists; saying so is more useful than pretending

Health (last success, last error, freshness) comes from feed_health and job_runs, which the
ingestion layer already writes. This module reads them; it never calls an external API itself.
"""
from __future__ import annotations

from . import config

CONNECTED, NEEDS_KEY, UNAVAILABLE = "connected", "needs_key", "unavailable"

# Static description of every source. `feeds` names the feed_health rows it writes and `jobs` the
# scheduler jobs that drive it, so health can be joined on without a second registry.
CATALOG: list[dict] = [
    {
        "key": "alpaca", "label": "Alpaca Market Data", "kind": "market",
        "powers": "end-of-day prices — the price source, and how claim and call outcomes get scored",
        "state": None, "env": ["ALPACA_API_KEY_ID", "ALPACA_API_SECRET_KEY"],
        "signup_url": "https://app.alpaca.markets/signup",
        "note": ("Free tier: 200 requests/minute, unlimited history, and MANY SYMBOLS PER REQUEST, "
                 "which is the whole reason it replaced Tiingo — 500 symbols is five calls, not "
                 "500. The free feed is IEX rather than the consolidated tape. Measured against "
                 "our own Tiingo rows on 2026-09-14 over 1,324 day-pairs, closes differ by "
                 "0.398% on average, which passes the 0.5% migration gate — but that average "
                 "has a thin-name tail: DMLP 2.86% and JCTC 2.29% both exceed the 2% noise "
                 "floor outcomes are scored against, so on an illiquid symbol the feed alone "
                 "can move a verdict. Liquid names are unaffected. Full numbers in "
                 "docs/analysis/alpaca_vs_tiingo.md."),
        "feeds": [], "jobs": ["ingest_prices"],
    },

    {
        "key": "smtp", "label": "Outbound email (SMTP)", "kind": "auth",
        "powers": "email verification and password reset — without it a forgotten password is "
                  "unrecoverable",
        "state": None, "env": ["SMTP_HOST", "MAIL_FROM"],
        "signup_url": "https://resend.com",
        "note": "Any SMTP provider. Two transactional messages is well inside every free tier. "
                "Unconfigured, the app refuses to send rather than half-working — it will not "
                "silently drop a reset link.",
        "feeds": [], "jobs": [],
    },

    {
        "key": "google_oauth", "label": "Google Sign-In", "kind": "auth",
        "powers": "signing in without a password",
        "state": None, "env": ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"],
        "signup_url": "https://console.cloud.google.com/apis/credentials",
        "note": "Create an OAuth 2.0 Client ID of type 'Web application' and register the redirect "
                "URI <PUBLIC_BASE_URL>/api/auth/google/callback exactly. Listed here because it is "
                "an external dependency with a key like any other — but note it is the one entry "
                "on this page whose live handshake has never been exercised, only its parsing and "
                "validation logic. Email and password signup is unaffected either way.",
        "feeds": [], "jobs": [],
    },

    {
        "key": "sentry", "label": "Sentry", "kind": "platform",
        "powers": "server-side error tracking",
        "state": None, "env": ["SENTRY_DSN"], "signup_url": "https://sentry.io",
        "note": "Free tier. Optional by design and initialised with traces_sample_rate 0.0, so it "
                "reports errors and not performance traces. A DSN set without the sentry_sdk "
                "package installed logs a warning at startup rather than being silently ignored, "
                "which is the state this entry exists to make visible.",
        "feeds": [], "jobs": [],
    },
]

def _smtp_configured() -> bool:
    from . import mail
    return mail.configured()


def _google_oauth_configured() -> bool:
    from . import oauth
    return oauth.configured()


# One entry per catalog source with `state: None`, and `test_every_dynamic_source_has_a_config_check`
# asserts the two tables cannot drift apart. A catalog entry asking for its state to be computed
# with nothing here to compute it falls through to NEEDS_KEY forever: the source can never report
# connected however valid the credential, `check-source` refuses to run its probe, and the operator
# is told to add a key they already added. Alpaca shipped that way once.
_DYNAMIC = {
    "alpaca": config.alpaca_configured,
    "sentry": config.sentry_configured,
    "smtp": _smtp_configured,
    "google_oauth": _google_oauth_configured,
}


def _state(src: dict) -> str:
    if src["state"] is not None:
        return src["state"]
    check = _DYNAMIC.get(src["key"])
    return CONNECTED if check and check() else NEEDS_KEY


def catalog() -> list[dict]:
    """Every source with its live configured state. No database, no network — cheap to call."""
    return [{**s, "state": _state(s)} for s in CATALOG]


def by_key(key: str) -> dict | None:
    return next((s for s in catalog() if s["key"] == key), None)


def gate(key: str) -> dict:
    """What the UI needs to render a degradation gate in place of a panel: the state, what the
    source would add, where to get the key, and the exact environment variables to set. Used
    wherever a feature is thin because a source is missing."""
    s = by_key(key)
    if not s:
        return {"key": key, "state": UNAVAILABLE, "label": key, "powers": "", "note": "Unknown source."}
    return {"key": s["key"], "label": s["label"], "state": s["state"], "powers": s["powers"],
            "note": s["note"], "signup_url": s["signup_url"], "env": s["env"]}


def health(conn, detailed: bool = False) -> list[dict]:
    """The catalog joined to what actually happened: last successful fetch per feed, freshest record,
    row counts, rejects, and whether the last job run failed. This is the whole point of the
    integration status page — no more guessing why a panel is empty.

    `detailed` (admins only) includes the raw error TEXT. That text is `str(exc)[:300]` of an
    arbitrary ingestion exception, and an httpx error embeds the full request URL including its
    query string — which is how a keyed API's credential would escape. Non-admins learn that a run
    failed, which is all they need to interpret an empty panel."""
    iso = lambda t: t.isoformat() if t else None                      # noqa: E731 — trivial local
    with conn.cursor() as cur:
        cur.execute("SELECT source, last_success_at, last_record_knowable, records_total, "
                    "rejects_total FROM feed_health")
        feeds = {r[0]: {"source": r[0], "last_success_at": r[1], "freshest": r[2],
                        "records": r[3], "rejects": r[4]} for r in cur.fetchall()}
        cur.execute("""SELECT DISTINCT ON (job) job, finished_at, status, duration_ms, detail
                       FROM job_runs ORDER BY job, started_at DESC""")
        jobs = {r[0]: {"job": r[0], "last_run": r[1], "status": r[2], "duration_ms": r[3],
                       "error": (r[4] or {}).get("message") if r[2] == "error" else None}
                for r in cur.fetchall()}
    out = []
    for s in catalog():
        mine = [feeds[f] for f in s["feeds"] if f in feeds]
        myjobs = [jobs[j] for j in s["jobs"] if j in jobs]
        # A job that no-ops because its source is unkeyed still records status 'ok'. Reporting that
        # as a successful fetch would tell the owner Reddit is working when it has never run.
        connected = s["state"] == CONNECTED
        last = [x["last_success_at"] for x in mine if x["last_success_at"]] + \
               ([j["last_run"] for j in myjobs if j["last_run"] and j["status"] == "ok"]
                if connected else [])
        errors = [j["error"] for j in myjobs if j.get("error")]
        out.append({
            **s,
            "feeds": [{**f, "last_success_at": iso(f["last_success_at"]), "freshest": iso(f["freshest"])}
                      for f in mine],
            "jobs": [{"job": j["job"], "last_run": iso(j["last_run"]), "status": j["status"],
                      "duration_ms": j["duration_ms"]} for j in myjobs],
            "last_success_at": iso(max(last)) if last else None,
            "records": sum(x["records"] or 0 for x in mine) or None,
            "rejects": sum(x["rejects"] or 0 for x in mine) or None,
            "failing": bool(errors),
            "last_error": (errors[0] if errors else None) if detailed else None,
        })
    return out
