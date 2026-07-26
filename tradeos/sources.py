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
        "key": "tiingo", "label": "Tiingo", "kind": "market",
        "powers": "end-of-day prices, which is how claim outcomes get scored",
        "state": None, "env": ["TIINGO_API_KEY"], "signup_url": "https://www.tiingo.com/account/api/token",
        "note": "Free tier is enough for daily bars on the names we track.",
        "feeds": [], "jobs": [],
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

# Sources whose state is computed from config rather than fixed.
_DYNAMIC = {
    "tiingo": lambda: bool(config.tiingo_configured()),
    "reddit": config.reddit_configured,
    "youtube": config.youtube_configured,
    "openfigi": lambda: bool(config.openfigi_configured()),
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
