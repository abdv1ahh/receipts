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
        "key": "sec_edgar", "label": "SEC EDGAR", "kind": "filings",
        "powers": "Smart Money — 13D/G stakes, Form 4 insider trades, 13F holdings, 8-K events",
        "state": CONNECTED, "env": ["SEC_USER_AGENT"], "signup_url": None,
        "note": "Free and keyless; SEC fair-access policy only requires a contact address in the "
                "User-Agent, which is already set.",
        "feeds": ["edgar/13dg", "edgar/form4", "edgar/13f", "sec/8-k"],
        "jobs": ["news_sec"],
    },
    {
        # `feeds` is filled from news_rss.FEEDS at the bottom of this module rather than typed out
        # here: the hand-kept copy listed four feeds long after the real list had grown to eleven,
        # so the status page under-reported which outlets this product actually reads.
        "key": "rss", "label": "News RSS (global)", "kind": "news",
        "powers": "News Intelligence, the source-comparison view, and the Morning Brief",
        "state": CONNECTED, "env": [], "signup_url": None,
        "note": "Free, keyless, public feeds, spanning several countries — the source-comparison "
                "view needs outlets that can actually disagree.",
        "feeds": [], "jobs": ["news_rss"],
    },
    {
        "key": "gdelt", "label": "GDELT", "kind": "news",
        "powers": "worldwide event coverage behind the Radar — the widest geographic net here",
        "state": CONNECTED, "env": [], "signup_url": None,
        "note": "Free and keyless. GDELT throttles on the User-Agent rather than the address, so a "
                "429 is answered by backing off and waiting rather than by rotating identity; a gap "
                "in coverage is preferable to evading a rate limit. Writes no per-feed health row, "
                "so freshness here is the scheduler job's own last run.",
        "feeds": [], "jobs": ["gdelt"],
    },
    {
        "key": "nasdaq_calendar", "label": "Nasdaq calendar", "kind": "calendar",
        "powers": "the earnings and macro calendar",
        "state": CONNECTED, "env": [], "signup_url": None, "note": "Free, keyless.",
        "feeds": ["nasdaq/earnings", "nasdaq/economic"], "jobs": ["earnings_cal", "economic_cal"],
    },
    {
        "key": "wikipedia", "label": "Wikipedia pageviews", "kind": "attention",
        "powers": "the attention board (measures attention, not mood)",
        "state": CONNECTED, "env": [], "signup_url": None,
        "note": "Free, keyless. Only names whose Wikipedia article is disambiguated to the company "
                "are counted, so a ticker cannot inherit a common word's traffic.",
        "feeds": [], "jobs": ["attention_wiki"],
    },
    {
        "key": "hn", "label": "Hacker News", "kind": "attention",
        "powers": "technology attention on the attention board",
        "state": CONNECTED, "env": [], "signup_url": None, "note": "Free, keyless (Algolia API).",
        "feeds": [], "jobs": ["sentiment_hn"],
    },
    {
        "key": "coingecko", "label": "CoinGecko", "kind": "market",
        "powers": "crypto prices, moves and search-trending",
        "state": CONNECTED, "env": [], "signup_url": None, "note": "Free tier, keyless.",
        "feeds": [], "jobs": [],
    },
    {
        "key": "binance", "label": "Binance public derivatives", "kind": "market",
        "powers": "the Crypto positioning read — funding rate, open interest, long/short crowding",
        "state": CONNECTED, "env": [], "signup_url": None,
        "note": "Free and keyless public endpoints (fapi.binance.com), verified 2026-07-25. Reads "
                "POSITIONING, not price: funding is what longs pay shorts on a perpetual, so a "
                "persistently positive rate measures crowding rather than direction.",
        "feeds": [], "jobs": ["crypto_structure"],
    },
    {
        "key": "finra", "label": "FINRA short interest", "kind": "market",
        "powers": "consolidated short interest, ingested as context",
        "state": CONNECTED, "env": [], "signup_url": None,
        "note": "Free and keyless. Ingested and stored with a settlement date and a publication "
                "knowable_time roughly eight business days later, so point-in-time discipline "
                "holds. Nothing scores it yet: weighting it into convergence is a logged version "
                "bump behind ENABLE_SHORT_INTEREST (decision #31). Listed here because it is a "
                "live external dependency, and an operator watching a feed go quiet should be able "
                "to see it here rather than deduce it. There is no scheduler job: it runs from the "
                "CLI (`ingest-short-interest`) and has not been run on this instance, so the "
                "feed_health row it would write does not exist yet and this entry will show no "
                "last success. That is the true state, not a fault.",
        "feeds": ["finra:consolidated"], "jobs": [],
    },
    {
        "key": "llm_gemini", "label": "Gemini (model provider 1)", "kind": "model",
        "powers": "every AI prose surface: the impact engine, the news analyst, chart reads, the "
                  "journal coach, the assistant",
        "state": None, "env": ["GEMINI_API_KEY"],
        "signup_url": "https://aistudio.google.com/apikey",
        "note": "Free tier. First link in the EXPLAIN_PROVIDER chain. The allowance is per MODEL "
                "and per day, so a working key can still exhaust; llm.py cools a provider for 120s "
                "after persistent 429s and falls through to the next link.",
        "feeds": [], "jobs": [],
    },
    {
        "key": "llm_openai", "label": "OpenAI-compatible (model provider 2, fallback)",
        "kind": "model",
        "powers": "the fallback for every AI prose surface when Gemini is out of quota or cooling",
        "state": None, "env": ["OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_MODEL"],
        "signup_url": "https://console.groq.com/keys",
        "note": "Second link in the EXPLAIN_PROVIDER chain, and the reason this entry exists: the "
                "slot pointed at GitHub Models, which now answers HTTP 410 "
                "'github_models_retirement_brownout' on every request, and this page could not say "
                "so because the chain was not in this registry at all. It is named for the "
                "PROTOCOL, not a vendor — Groq, OpenRouter and OpenAI itself all speak it, so "
                "repointing it is three environment variables and no code. Groq's free tier needs "
                "no card. Set OPENAI_BASE_URL, OPENAI_API_KEY and OPENAI_MODEL in BOTH .env and "
                "docker-compose.yml, which enumerates every variable it passes through.",
        "feeds": [], "jobs": [],
    },
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
        "key": "reddit", "label": "Reddit", "kind": "social",
        "powers": "discussion volume AND sentiment — the only connected source that measures mood, "
                  "not just attention",
        "state": None, "env": ["REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET"],
        "signup_url": "https://www.reddit.com/prefs/apps",
        "note": "Free, but it has to be created by hand. On the linked page choose 'create another "
                "app', pick type **script**, and put anything valid in 'redirect uri' "
                "(http://localhost:8000 works — this app never uses it, but Reddit's form will not "
                "submit without one). The client id is the string UNDER the app name, not the app "
                "name itself. Put both in .env at the repository root as REDDIT_CLIENT_ID and "
                "REDDIT_CLIENT_SECRET, then `docker compose up -d` to restart, and confirm with "
                "`docker compose exec -T api python -m tradeos.cli check-source reddit`, which "
                "makes a real call and reports what came back. There is no useful keyless mode — "
                "Reddit blocks the public JSON endpoints from datacenter addresses, so we ask "
                "rather than quietly returning nothing.",
        "feeds": [], "jobs": ["social_reddit"],
    },
    {
        "key": "youtube", "label": "YouTube", "kind": "social",
        "powers": "video discussion volume and sentiment",
        "state": None, "env": ["YOUTUBE_API_KEY"],
        "signup_url": "https://console.cloud.google.com/apis/library/youtube.googleapis.com",
        "note": "Free Data API quota is small; used sparingly.", "feeds": [], "jobs": [],
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
        "key": "openfigi", "label": "OpenFIGI", "kind": "reference",
        "powers": "mapping 13F CUSIPs to tickers — unmapped holdings are invisible everywhere",
        "state": None, "env": ["OPENFIGI_API_KEY"], "signup_url": "https://www.openfigi.com/api",
        "note": "Works without a key at a low rate limit; a free key raises it.",
        "feeds": [], "jobs": [],
    },
    {
        "key": "bluesky", "label": "Bluesky", "kind": "social",
        "powers": "posts from consequential accounts — the open-network answer to X being shut",
        "state": CONNECTED, "env": [], "signup_url": None,
        "note": "Free and keyless. Reads a curated list of consequential accounts "
                "(watchlist_accounts, platform 'bluesky') rather than searching the network: "
                "Bluesky's keyless search endpoint returns 403 as of 2026-07-26, so network-wide "
                "keyword search is not available without an account. Reposts are skipped — an "
                "account amplifying someone else is not that account speaking.",
        "feeds": [], "jobs": ["social_bluesky"],
    },
    {
        "key": "stocktwits", "label": "StockTwits", "kind": "social",
        "powers": "retail chatter", "state": UNAVAILABLE, "env": [], "signup_url": None,
        "note": "No free read tier. Left disconnected rather than faked.", "feeds": [], "jobs": [],
    },
    {
        "key": "x", "label": "X / Twitter", "kind": "social",
        "powers": "posts from consequential accounts",
        "state": UNAVAILABLE, "env": [], "signup_url": None,
        "note": "X's free API tier does not permit reading timelines and the paid tiers start well "
                "beyond free-tier scope. Scraping breaks their terms and breaks constantly, so it is "
                "not shipped, and it is not coming back by being wished at. The need it was meant "
                "to serve — knowing what consequential people are saying — is served instead by "
                "Bluesky (curated accounts, live above), by the official channels in the "
                "consequential-accounts list, and by the news wires, which carry a public "
                "statement within minutes. This entry stays visible so the gap is stated rather "
                "than quietly dropped.",
        "feeds": [], "jobs": [],
    },
    {
        "key": "stripe", "label": "Stripe", "kind": "platform",
        "powers": "subscription billing — checkout, the customer portal, and the webhook that "
                  "moves a user between tiers",
        "state": None, "env": ["STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET"],
        "signup_url": "https://dashboard.stripe.com/test/apikeys",
        "note": "Unset, the app runs in free launch mode: the pricing page still renders and every "
                "signup gets the paid tier, rather than a checkout button that 500s. The webhook "
                "handler verifies the Stripe signature and refuses an unsigned payload, so the "
                "webhook secret is not optional once the secret key is set. Test mode throughout.",
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

def _fill_rss_feeds() -> None:
    """Point the rss entry at the real feed list. Imported lazily and inside a function so this
    module keeps its "no network, no database, cheap to import" property, and so a failure to import
    an ingestion module degrades the status page rather than taking the whole app down."""
    try:
        from .ingestion.news_rss import FEEDS
    except Exception:  # pragma: no cover - a broken ingestion import must not break the registry
        return
    for src in CATALOG:
        if src["key"] == "rss":
            src["feeds"] = [f"rss/{f.key}" for f in FEEDS]


_fill_rss_feeds()

# Sources whose state is computed from config rather than fixed. EVERY catalog entry declaring
# `"state": None` must appear here: `_state` falls through to NEEDS_KEY when it finds no check, so
# an omission does not degrade, it LIES — the source reports "add a key" forever however valid the
# credential is, `check-source` refuses to run its probe, and the operator is told to fix something
# they already fixed. Alpaca, SMTP and Google OAuth all shipped missing. A test pins the two tables
# together; do not add a dynamic source without adding its check here.
#
# `mail` and `oauth` are imported inside the check, not at module scope, to keep this module's
# "no network, no database, cheap to import" property — the same reason `_fill_rss_feeds` defers
# its ingestion import.


def _smtp_configured() -> bool:
    from . import mail
    return mail.configured()


def _google_oauth_configured() -> bool:
    from . import oauth
    return oauth.configured()


_DYNAMIC = {
    "alpaca": config.alpaca_configured,
    "reddit": config.reddit_configured,
    "youtube": config.youtube_configured,
    "openfigi": lambda: bool(config.openfigi_configured()),
    "llm_gemini": config.gemini_configured,
    "llm_openai": config.openai_compat_configured,
    "stripe": config.stripe_configured,
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
