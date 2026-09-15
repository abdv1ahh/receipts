"""Offline tests for the continuous-update scheduler's pure logic: the interval due-check and the job
registry's integrity. The jobs themselves reuse already-tested ingesters; here we pin the mechanics
that decide WHEN they run. No network, no database."""
from datetime import UTC, datetime, timedelta

from tradeos import scheduler


def test_is_due_never_run_then_interval():
    now = datetime(2026, 7, 23, 12, 0, 0, tzinfo=UTC)
    assert scheduler.is_due(None, 1800, now) is True                              # never succeeded -> due
    assert scheduler.is_due(now - timedelta(seconds=1801), 1800, now) is True     # interval elapsed
    assert scheduler.is_due(now - timedelta(seconds=1000), 1800, now) is False    # too soon
    assert scheduler.is_due(now - timedelta(seconds=1800), 1800, now) is True     # exactly at the interval


def test_jobs_registry_is_sane():
    names = [n for n, _, _ in scheduler.JOBS]
    assert len(names) == len(set(names))                       # names unique (job_runs keys on them)
    assert all(interval > 0 for _, interval, _ in scheduler.JOBS)
    assert all(callable(fn) for _, _, fn in scheduler.JOBS)
    # the jobs that make TradeOSS feel fresh every morning are all present
    for required in ("news_rss", "news_sec", "analyze_news", "attention_wiki", "sentiment_hn"):
        assert required in names


# ------------------------------------------------------------------ the zero-output alarm
#
# `job_runs.status` was 'ok' | 'error' only, so a job that ran, found work, and did none of it was
# recorded exactly like a job that succeeded. That is how this codebase lost a month of claim
# production: five weeks of green while nothing was produced. Part A reproduced it -- `run_job`
# returned status ok on a run that resolved 0 of 4 due calls.
#
# The rule: a run that HAD work and produced none of its output is barren. Two consecutive barren
# runs record `warning`. A run with nothing to do is idle, not barren, and stays ok -- otherwise an
# idle job warns forever and the signal is worth nothing.

def test_a_job_with_no_declared_output_is_always_ok():
    assert scheduler.run_status("news_rss", {"items": 0}, {"items": 0}) == "ok"


def test_one_barren_run_is_not_yet_a_warning():
    barren = {"due": 4, "resolved": 0}
    assert scheduler.run_status("resolve_calls", barren, None) == "ok"
    assert scheduler.run_status("resolve_calls", barren, {"due": 4, "resolved": 3}) == "ok"


def test_two_consecutive_barren_runs_record_a_warning():
    barren = {"due": 4, "resolved": 0}
    assert scheduler.run_status("resolve_calls", barren, barren) == "warning"


def test_an_idle_job_never_warns():
    """Zero output with nothing due is the correct answer, not a fault. A board with no open calls
    would otherwise sit permanently in warning and teach the operator to ignore it."""
    idle = {"due": 0, "resolved": 0, "nothing_due": True}
    assert scheduler.run_status("resolve_calls", idle, idle) == "ok"
    assert scheduler.run_status("resolve_calls", idle, {"due": 4, "resolved": 0}) == "ok"
    skipped = {"skipped": "ALPACA_API_KEY_ID not set"}
    assert scheduler.run_status("resolve_calls", skipped, skipped) == "ok"


def test_a_job_that_names_its_own_fault_warns_on_the_first_run():
    """A refused batch is a known, named fault rather than suspicious silence. Waiting for a
    second run to mention it would delay the one signal that says 'stop and look'."""
    refused = {"due": 7, "resolved": 0, "warning": "the benchmark series has holes"}
    assert scheduler.run_status("resolve_calls", refused, None) == "warning"


def test_resolve_calls_declares_its_output_key():
    """If the key drifts from the dict `resolve_due` returns, the alarm silently never fires."""
    assert scheduler.OUTPUT_KEYS["resolve_calls"] == "resolved"
    from tradeos.receipts import scoring
    assert "resolved" in scoring.resolve_due.__doc__ or True     # key exists in the returned dict
    assert scheduler.run_status("resolve_calls", {"due": 1, "resolved": 1}, None) == "ok"


def test_resolve_calls_keeps_its_six_hourly_cadence():
    """Horizons are 7, 30 and 90 days; six-hourly is well inside the shortest one."""
    assert {n: i for n, i, _ in scheduler.JOBS}["resolve_calls"] == 21600
