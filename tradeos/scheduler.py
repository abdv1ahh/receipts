"""The background worker: get the prices, then score what the prices have made scoreable.

A dependency-free worker: a registry of (name, interval, fn) jobs, a due-check driven by the last
successful run in `job_runs` (so it survives restarts), and per-job error isolation — one failing
job never stops the other, and it degrades LOUDLY into `job_runs` rather than quietly. Runs as its
own container (`python -m tradeos.cli scheduler`), keeping the API process stateless.

THE MOST IMPORTANT THING HERE IS `run_status`, not the jobs. A scheduler that records "ok" for a
run that produced nothing is how a month of zero claim production went unnoticed in this codebase.
A job with work to do that produces none of it on two consecutive runs is recorded as `warning`,
and with two jobs left there is nowhere for that signal to hide.
"""
from __future__ import annotations

import logging
import time
from datetime import UTC, datetime, timedelta

from psycopg.types.json import Json

from . import db

log = logging.getLogger("tradeos.scheduler")


# ------------------------------------------------------------------ job implementations

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


def _job_ingest_prices(conn) -> dict:
    """Keep end-of-day prices current. NEW — there was no price job here at all.

    That absence is why prices went stale. Ingestion was CLI-only, driven by a paced shell script
    an operator had to remember to run, because free Tiingo allows one symbol per request at ~50
    requests an hour: 500 symbols could not be refreshed inside a scheduler tick, so nobody tried.
    Measured 2026-09-09, the consequence was 0 of 500 symbols holding a bar at the latest session.

    Alpaca removes the constraint rather than managing it — many symbols per request, 200 requests
    a minute — so 500 symbols is five calls and this becomes an ordinary job.

    The work list is `symbols_stale`, which is ordered OLDEST-DATA-FIRST. If a tick is cut short,
    the symbols it skipped are the freshest ones and they sort to the front next time. SPY leads
    regardless, because a stale benchmark unscoreables everything else.
    """

    from . import config
    from .ingestion.prices_alpaca import AlpacaClient, ingest_prices_alpaca, symbols_stale

    if not config.alpaca_configured():
        # A source that no-ops because it is unkeyed still records status ok in job_runs, and
        # `sources.health()` deliberately does not count that as a successful fetch. Say which
        # key is missing rather than leaving a silent zero.
        return {"skipped": "ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY not set"}

    with conn.cursor() as cur:
        cur.execute("SELECT max(day) FROM prices_eod")
        newest = cur.fetchone()[0]
    if newest is None:
        return {"skipped": "prices_eod is empty; run a backfill first"}

    symbols = symbols_stale(conn, newest)
    if not symbols:
        return {"nothing_due": True, "note": f"every symbol already reaches {newest}"}

    key_id, secret = config.alpaca_credentials()
    client = AlpacaClient(key_id, secret)
    try:
        # Reach back a fortnight rather than to `newest`: a symbol that was halted or thinly traded
        # can have a gap, and re-requesting a few extra sessions is free in a batched call.
        out = ingest_prices_alpaca(conn, client, symbols, newest - timedelta(days=14))
    finally:
        client.close()
    log.info("ingest_prices: %d symbols, %d batches, %d rows (rate_limited=%s)",
             out["symbols"], out["batches"], out["rows"], out["rate_limited"])
    return out


JOBS = [
    # TWO JOBS, DOWN FROM TWENTY-ONE. Nineteen of them fed the interpretation plane — RSS, SEC
    # 8-Ks, GDELT, Bluesky, Reddit, Hacker News, Wikipedia pageviews, two calendars, the spine, the
    # claim engine and its re-interpretation pass, the radar alert queue, the brief warmer and the
    # crypto structure poll. What is left is the whole of what Receipts needs to keep working
    # without anybody touching it: get the prices, then score what the prices have made scoreable.
    #
    # Daily bars change once a day, but a pass can be cut short, so check every 6h. Batched
    # against Alpaca the whole table is ~48 requests.
    ("ingest_prices", 21600, _job_ingest_prices),
    # Horizons are 7, 30 and 90 days, so nothing is gained by checking more often than the price
    # feed itself moves. Four times a day is well inside the shortest horizon, and it runs AFTER
    # prices on the same tick, which is the order that matters: scoring against a feed that has
    # not been topped up is how a call stays open for an extra six hours for no reason.
    ("resolve_calls", 21600, _job_resolve_calls),
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
        # 'warning' counts as having run. A warning means the job completed and produced nothing,
        # not that it needs retrying sooner — and treating it as never-succeeded would make a job
        # in warning run on every single tick, which is the opposite of what an alarm should do.
        cur.execute("SELECT max(finished_at) FROM job_runs WHERE job=%s AND status IN ('ok', "
                    "'warning')", (job,))
        return cur.fetchone()[0]


# ------------------------------------------------------------------ the zero-output alarm
#
# `job_runs.status` was 'ok' | 'error'. So a job that ran, found work, and did none of it was
# recorded exactly like a job that succeeded — and this codebase has already paid for that once:
# five weeks of green while the claim engine produced nothing, because "did not crash" and "did
# its job" were the same value. The Part A proof run reproduced it exactly, with `run_job`
# returning status ok on a run that resolved 0 of 4 due calls.
#
# Which detail key counts as a job's OUTPUT. Only jobs listed here can warn; the rest are
# unchanged, because a threshold invented for a job nobody has thought about is noise, and an
# alarm that cries wolf gets switched off. `resolve_calls` first, since it is the one whose silence
# costs a caller their record.
OUTPUT_KEYS = {"resolve_calls": "resolved"}


def _barren(detail: dict, key: str) -> bool:
    """True if this run HAD work to do and produced none of its output.

    The distinction between barren and idle is what makes the alarm worth having. A board with no
    open calls legitimately scores nothing every six hours forever; warning on that would leave the
    status permanently amber and teach the operator to ignore it, which is worse than no alarm. A
    job says it was idle by returning `nothing_due` or `skipped`, both of which already exist.
    """
    if detail.get("nothing_due") or detail.get("skipped"):
        return False
    return not detail.get(key)


def run_status(job: str, detail: dict, previous: dict | None) -> str:
    """'ok' or 'warning' for a run that did not raise. Pure.

    Two ways to warn, and they are deliberately different in urgency:

      NAMED FAULT.   The job returned a `warning` key — it knows what is wrong and says so. Warns
                     on the FIRST run, because waiting for a second would delay the one signal
                     that means "stop and look". `resolve_due` sets this when it refuses a batch.
      SUSPICIOUS     Two consecutive barren runs. One barren run can be a race with an ingestion
      SILENCE.       pass that is still working; two in a row is a pattern.
    """
    if detail.get("warning"):
        return "warning"
    key = OUTPUT_KEYS.get(job)
    if key is None:
        return "ok"
    if _barren(detail, key) and previous is not None and _barren(previous, key):
        return "warning"
    return "ok"


def _previous_detail(conn, job: str) -> dict | None:
    """The last non-error run's detail for this job, or None if there has never been one.

    Errors are skipped rather than counted as barren: a run that raised has no output dict to
    judge, and it is already recorded as `error`, which is louder than a warning.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT detail FROM job_runs WHERE job=%s AND status <> 'error' "
                    "ORDER BY id DESC LIMIT 1", (job,))
        row = cur.fetchone()
    return row[0] if row and isinstance(row[0], dict) else None


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
    previous = _previous_detail(conn, name) if name in OUTPUT_KEYS else None
    try:
        detail = fn(conn) or {}
        status = run_status(name, detail, previous)
        if status == "warning":
            log.warning("job %s produced nothing: %s", name,
                        detail.get("warning") or detail.get("note") or "no output on two runs")
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
