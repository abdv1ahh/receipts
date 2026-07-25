"""Tests for the source registry and the integration status surface.

Includes the fix for the finding this phase's own security review raised: /api/integrations was
unauthenticated and returned `str(exc)` from arbitrary ingestion failures, and httpx puts the full
request URL — query string included — into its exception messages. A keyed API's credential could
therefore reach the database and then the public internet."""
import pytest

from tradeos import scheduler, sources

# ------------------------------------------------------------------ the registry

def test_catalog_states_are_derived_from_config(monkeypatch):
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
    assert sources.by_key("reddit")["state"] == sources.NEEDS_KEY
    monkeypatch.setenv("REDDIT_CLIENT_ID", "id")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "secret")
    assert sources.by_key("reddit")["state"] == sources.CONNECTED


def test_sources_with_no_free_path_stay_unavailable_not_needs_key():
    """X and StockTwits must never render as 'add a key' — there is no key to add."""
    assert sources.by_key("x")["state"] == sources.UNAVAILABLE
    assert sources.by_key("stocktwits")["state"] == sources.UNAVAILABLE
    assert sources.by_key("sec_edgar")["state"] == sources.CONNECTED


def test_gate_carries_what_the_ui_needs_to_explain_itself(monkeypatch):
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    g = sources.gate("reddit")
    assert g["state"] == sources.NEEDS_KEY
    assert g["signup_url"].startswith("https://www.reddit.com/")
    assert "REDDIT_CLIENT_ID" in g["env"] and "REDDIT_CLIENT_SECRET" in g["env"]
    assert g["powers"]                                   # never an empty explanation


def test_unknown_source_degrades_instead_of_raising():
    g = sources.gate("nope")
    assert g["state"] == sources.UNAVAILABLE and g["label"] == "nope"


# ------------------------------------------------------------------ credential redaction

@pytest.mark.parametrize("raw,expected", [
    ("Client error '400' for url 'https://x.googleapis.com/v1/models:go?key=AIzaSECRET'",
     "Client error '400' for url 'https://x.googleapis.com/v1/models:go?<redacted>'"),
    ("failed https://api.tiingo.com/daily/AAPL?token=abc123&startDate=2026-01-01",
     "failed https://api.tiingo.com/daily/AAPL?<redacted>"),
    ("connection refused", "connection refused"),
    ("", ""),
])
def test_redact_strips_query_strings(raw, expected):
    """A credential passed as a URL parameter must never reach the database or the logs."""
    assert scheduler.redact(raw) == expected


def test_redact_leaves_no_key_material_behind():
    msg = "HTTPStatusError for url 'https://generativelanguage.googleapis.com/v1beta/m:g?key=AIzaLIVEKEY'"
    out = scheduler.redact(msg)
    assert "AIzaLIVEKEY" not in out and "key=" not in out
    assert "generativelanguage.googleapis.com" in out    # the host is still useful for debugging
