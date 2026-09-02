"""Continuous update scheduler (Milestone 3) — the piece that makes TradeOSS fresh when you open it.

A dependency-free worker: a registry of (name, interval, fn) jobs that reuse the existing ingestion
functions, a due-check driven by the last successful run in job_runs (so it survives restarts), and
per-job error isolation (one failing job never stops the others, and it degrades LOUDLY into job_runs).
Runs as its own container (`python -m tradeos.cli scheduler`), keeping the API process stateless.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import UTC, date, datetime, timedelta

from psycopg.types.json import Json

from . import db, sentiment, social

log = logging.getLogger("tradeos.scheduler")


# ------------------------------------------------------------------ job implementations

def _job_news_rss(conn) -> dict:
    from .ingestion import news_rss
    c = news_rss.RssClient()
    try:
        return news_rss.ingest(conn, c)
    finally:
        c.close()


def _job_news_sec(conn) -> dict:
    """The most recent business day whose daily index exists (today's often isn't published yet)."""
    from .config import sec_user_agent
    from .ingestion import news_sec
    from .ingestion.edgar_client import EdgarClient
    c = EdgarClient(sec_user_agent())
    try:
        out: dict = {}
        d = date.today()
        for _ in range(5):
            if d.weekday() < 5:
                try:
                    out[d.isoformat()] = news_sec.ingest_day(conn, c, d, limit=30)
                    break
                except Exception as exc:                     # missing index / holiday -> try the prior day
                    conn.rollback()
                    out[d.isoformat()] = f"skip: {type(exc).__name__}"
            d -= timedelta(days=1)
        return out
    finally:
        c.close()


def _job_analyze_news(conn) -> dict:
    from .intelligence import analyst
    return analyst.analyze_recent(conn, hours=48, limit=10)


def _job_sentiment_hn(conn) -> dict:
    from .ingestion.sentiment_hn import ingest_hn
    return {"written": ingest_hn(conn, sentiment.tracked_symbols(conn, limit=60))}


def _job_attention_wiki(conn) -> dict:
    from .ingestion import attention_wiki
    base = sentiment.tracked_symbols(conn, limit=60)
    return {"written": attention_wiki.ingest(conn, social.attention_universe(conn, base))}


def _job_social_reddit(conn) -> dict:
    from .ingestion import social_reddit
    return {"written": social_reddit.ingest(conn)}   # honest no-op until Reddit creds are set


def _job_earnings(conn) -> dict:
    from .ingestion import calendar_nasdaq
    return calendar_nasdaq.ingest_earnings(conn, days_ahead=14)


def _job_economic(conn) -> dict:
    from .ingestion import calendar_nasdaq
    return calendar_nasdaq.ingest_economic(conn, days_ahead=12)


def _job_gdelt(conn) -> dict:
    """The global news backbone. Paced internally; a 429 ends the pass rather than hammering."""
    from .ingestion import gdelt
    return gdelt.ingest(conn, timespan="2h")


def _job_social_bluesky(conn) -> dict:
    """The consequential-accounts feed on the one social network with an open read API. Keyless,
    so unlike Reddit this runs for real out of the box.

    A smaller window than the adapter's default because this runs hourly and the busiest account
    here posts about four times an hour, so twelve is ample. Note that this did NOT buy the speedup
    it looks like it should: measured 186s for 381 events and 165s for 183: the cost is per-event
    cluster matching, which scales with the CLUSTER CORPUS rather than with the batch. See
    `spine.find_cluster` — it computes similarity() against every cluster in the window (821 of
    them) with no trigram index, because `similarity(a,b) >= c` cannot use one; only the `%`
    operator can, and that reads its threshold from a session GUC. Making it indexable is a real
    change to the matching path and clustering correctness is load-bearing, so it is written up
    rather than done in passing. Comfortably inside the hour either way."""
    from .ingestion import social_bluesky
    return social_bluesky.ingest(conn, limit=12)


def _job_spine_news(conn) -> dict:
    """Project newly-arrived news_items into the event spine, so a story reported by both CNBC and
    GDELT clusters as one happening. Small window — the bootstrap backfill is a CLI command."""
    from .ingestion import news_adapter
    return news_adapter.backfill(conn, since_hours=6)


def _job_interpret(conn) -> dict:
    """Turn the most consequential new clusters into claims. Bounded — inference is the scarcest
    resource here, so it is spent on high-novelty events rather than everything that arrived."""
    from . import claims
    return claims.interpret_recent(conn, hours=6, limit=6)


def _job_measure_claims(conn) -> dict:
    """Score every claim whose horizon has elapsed, then pick up any newly-closed signal-plane
    outcomes. This is what makes the Ledger a record rather than a collection of opinions."""
    from . import ledger, smartmoney_claims
    out = ledger.measure_due(conn)
    imported = smartmoney_claims.build(conn, horizon_days=30)
    return {**out, "signal_claims_imported": imported["claims_made"]}


def _job_resolve_calls(conn) -> dict:
    """Score every published call whose horizon has closed.

    The detail this returns is the whole reason it returns a dict rather than None. A job that
    produced nothing is still recorded as a successful run, which is exactly how a month of zero
    claim production went unnoticed in this codebase, so `resolve_due` reports counts BY VERDICT
    and says explicitly when nothing was due. `job_runs.detail` then answers "what did it actually
    do" instead of only "did it crash".
    """
    from .receipts import scoring
    out = scoring.resolve_due(conn)
    if out.get("nothing_due"):
        log.info("resolve_calls: nothing due (%s)", out.get("note", ""))
    else:
        log.info("resolve_calls: %d due, %d resolved (%dH/%dM/%dI/%dU)", out["due"],
                 out["resolved"], out.get("hit", 0), out.get("miss", 0),
                 out.get("inconclusive", 0), out.get("unscoreable", 0))
    return out


def _job_crypto_structure(conn) -> dict:
    """Keep the derivatives cache warm so the Crypto surface is instant. Five symbols x four
    endpoints is ~7s of paced requests — fine here, unacceptable on a page load."""
    from .ingestion import derivatives
    out = derivatives.fetch_cached()
    return {"symbols": len(out.get("positioning") or {}), "failed": out.get("failed")}


def _job_warm_brief(conn) -> dict:
    """Pre-compute + cache the shared market Morning Brief so it's instant to open. Runs after the news
    jobs so the LLM circuit is already warm and the brief reflects the latest data. Lazy app import
    keeps the worker decoupled (app imports scheduler, not the reverse, at module load)."""
    from . import brief
    from .app import _voice_names
    with conn.cursor() as cur:
        cur.execute("SELECT max(as_of) FROM signal_clusters")
        as_of = cur.fetchone()[0]
    b = brief.cached_compose(conn, user_id=None, as_of=as_of, tier="pro", delayed_hours=0,
                             followed_symbols=[], provider=os.environ.get("EXPLAIN_PROVIDER", "template"),
                             voice_name_fn=_voice_names)
    return {"from_cache": b.get("from_cache"), "news": len(b.get("what_changed") or []),
            "coming": len(b.get("whats_coming") or [])}


# name, interval_seconds, fn — intervals chosen for how fast each source actually moves
def _job_reinterpret(conn):
    """Re-read stories that have developed since their last claim (Phase 4 threading). Runs after
    `interpret` on the same tick so a cluster that just gained sources is considered promptly."""
    from . import claims
    return claims.reinterpret_developing(conn, hours=72, limit=3)


def _job_radar_alerts(conn):
    """Deliver subscriptions whose throttle has elapsed. The per-filter throttle is the real
    control; this only decides how often the queue is looked at."""
    from . import radar
    return radar.deliver_due(conn)


JOBS = [
    ("news_rss", 1800, _job_news_rss),        # headlines move -> every 30 min
    ("news_sec", 21600, _job_news_sec),       # 8-K filings -> every 6h
    ("analyze_news", 3600, _job_analyze_news),  # interpret the new items -> hourly
    ("sentiment_hn", 21600, _job_sentiment_hn),  # every 6h
    ("attention_wiki", 86400, _job_attention_wiki),  # pageviews are daily
    ("social_reddit", 3600, _job_social_reddit),  # hourly (no-op until configured)
    # 16 accounts, one request each. The requests are the cheap part (~20s paced); the cost is the
    # spine re-clustering every post fetched, measured at 186s for a 25-post window — hence the
    # smaller window in the job. Still comfortably inside the hour, so passes never overlap.
    ("social_bluesky", 3600, _job_social_bluesky),  # hourly; keyless, so it runs by default
    ("earnings_cal", 43200, _job_earnings),       # forward earnings -> twice a day
    ("economic_cal", 43200, _job_economic),       # macro calendar -> twice a day
    ("warm_brief", 3600, _job_warm_brief),        # keep the shared brief hot (runs after the news jobs)
    # The spine. GDELT is paced at ~1 request per 5s internally, so a pass costs ~30s of wall time
    # for 5 queries; hourly keeps well inside what the free API tolerates.
    ("gdelt", 3600, _job_gdelt),
    ("spine_news", 1800, _job_spine_news),        # follows news_rss, which runs on the same tick
    ("interpret", 3600, _job_interpret),          # claims from new clusters, hourly and bounded
    # Re-interpretation is bounded harder than first interpretation: a revision spends the same
    # quota as a new claim and there are always more new events than developing ones.
    ("reinterpret", 7200, _job_reinterpret),      # developing stories -> every 2h, 3 at a time
    ("radar_alerts", 900, _job_radar_alerts),     # check the queue every 15 min; throttles are per filter
    ("measure_claims", 21600, _job_measure_claims),  # horizons close slowly; 4x a day is plenty
    ("crypto_structure", 240, _job_crypto_structure),  # just inside the 300s cache TTL
    # Horizons are 7, 30 and 90 days, so nothing is gained by checking more often than the price
    # feed itself moves. Four times a day is well inside the shortest horizon and leaves the free
    # Tiingo allowance to the ingestion jobs.
    ("resolve_calls", 21600, _job_resolve_calls),      # every 6h
]


# ------------------------------------------------------------------ due-logic (pure) + recording

def is_due(last_success: datetime | None, interval_s: int, now: datetime | None = None) -> bool:
    """True if a job has never succeeded or its interval has elapsed since the last success. Pure."""
    if last_success is None:
        return True
    now = now or datetime.now(UTC)
    return (now - last_success).total_seconds() >= interval_s


def _last_success(conn, job: str) -> datetime | None:
    with conn.cursor() as cur:
        cur.execute("SELECT max(finished_at) FROM job_runs WHERE job=%s AND status='ok'", (job,))
        return cur.fetchone()[0]


# A URL's query string is where credentials travel (Gemini authenticates with ?key=..., and other
# free APIs do the same). httpx puts the full request URL into its exception message, so an
# unhandled 4xx would otherwise write a live key into job_runs and into any surface that reads it.
# Strip every query string before the message is stored or logged.
#
# The rule now lives in `ingestion.common` because the ingestion adapters need it too — Tiingo
# authenticates with `?token=` and `reject()` had been storing it unredacted. `scheduler.redact` is
# re-exported rather than reimplemented: two copies of this would drift, and the copy that drifted
# would leak a key. Imported here so existing callers and tests keep working unchanged.
from .ingestion.common import redact  # noqa: E402  (placed with the reasoning it belongs to)


def run_job(conn, name: str, fn) -> dict:
    """Run one job, recording the attempt in job_runs whether it succeeds or fails (degrade loudly)."""
    started = datetime.now(UTC)
    t0 = time.monotonic()
    try:
        detail = fn(conn) or {}
        status = "ok"
    except Exception as exc:
        conn.rollback()
        detail = {"error": type(exc).__name__, "message": redact(str(exc))[:300]}
        status = "error"
        log.warning("job %s failed: %s: %s", name, type(exc).__name__, redact(str(exc))[:300])
    dur = int((time.monotonic() - t0) * 1000)
    with conn.cursor() as cur:
        cur.execute("INSERT INTO job_runs (job, started_at, finished_at, status, detail, duration_ms) "
                    "VALUES (%s,%s,now(),%s,%s,%s)", (name, started, status, Json(detail), dur))
    conn.commit()
    return {"job": name, "status": status, "duration_ms": dur, "detail": detail}


def run_once(conn, jobs=None, force: bool = False) -> list[dict]:
    """Run every job whose interval has elapsed (or all, if force). Returns per-job results."""
    ran = []
    for name, interval, fn in (jobs or JOBS):
        if force or is_due(_last_success(conn, name), interval):
            log.info("running job %s", name)
            ran.append(run_job(conn, name, fn))
    return ran


def run_forever(tick_seconds: int = 60) -> None:
    """The worker loop: every tick, run due jobs on a fresh connection (resilient to DB blips)."""
    log.info("scheduler starting (%d jobs, tick %ds)", len(JOBS), tick_seconds)
    while True:
        try:
            with db.connect() as conn:
                for r in run_once(conn):
                    log.info("job %s -> %s (%dms) %s", r["job"], r["status"], r["duration_ms"], r["detail"])
        except Exception as exc:   # never let a bad tick kill the worker
            log.error("scheduler tick failed: %s", exc)
        time.sleep(tick_seconds)


def job_status(conn) -> list[dict]:
    """Latest run per job — the honest 'is it fresh?' surface for /api/jobs."""
    out = []
    with conn.cursor() as cur:
        for name, interval, _ in JOBS:
            cur.execute("SELECT finished_at, status, duration_ms FROM job_runs WHERE job=%s "
                        "ORDER BY started_at DESC LIMIT 1", (name,))
            r = cur.fetchone()
            out.append({"job": name, "interval_s": interval,
                        "last_run": r[0].isoformat() if r and r[0] else None,
                        "status": r[1] if r else None, "duration_ms": r[2] if r else None})
    return out
