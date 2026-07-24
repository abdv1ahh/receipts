"""Offline tests for the continuous-update scheduler's pure logic: the interval due-check and the job
registry's integrity. The jobs themselves reuse already-tested ingesters; here we pin the mechanics
that decide WHEN they run. No network, no database."""
from datetime import datetime, timedelta, timezone

from tradeos import scheduler


def test_is_due_never_run_then_interval():
    now = datetime(2026, 7, 23, 12, 0, 0, tzinfo=timezone.utc)
    assert scheduler.is_due(None, 1800, now) is True                              # never succeeded -> due
    assert scheduler.is_due(now - timedelta(seconds=1801), 1800, now) is True     # interval elapsed
    assert scheduler.is_due(now - timedelta(seconds=1000), 1800, now) is False    # too soon
    assert scheduler.is_due(now - timedelta(seconds=1800), 1800, now) is True     # exactly at the interval


def test_jobs_registry_is_sane():
    names = [n for n, _, _ in scheduler.JOBS]
    assert len(names) == len(set(names))                       # names unique (job_runs keys on them)
    assert all(interval > 0 for _, interval, _ in scheduler.JOBS)
    assert all(callable(fn) for _, _, fn in scheduler.JOBS)
    # the jobs that make TradeOS feel fresh every morning are all present
    for required in ("news_rss", "news_sec", "analyze_news", "attention_wiki", "sentiment_hn"):
        assert required in names
