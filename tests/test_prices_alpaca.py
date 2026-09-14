"""Offline tests for the Alpaca price client.

All three pin behaviour that was found broken against the LIVE free tier on 2026-09-14, the day
the key was first configured. The module shipped with none of this covered, and every one of the
faults was silent: the pass reported batches attempted and rows zero, which reads like an empty
market rather than a malformed request.
"""
from datetime import date

import httpx
import pytest

from tradeos.ingestion.prices_alpaca import AlpacaClient


def _client(handler) -> AlpacaClient:
    """A real AlpacaClient with its transport swapped, so request BUILDING is what gets tested."""
    c = AlpacaClient("key-id", "secret", min_interval=0.0)
    c._client = httpx.Client(transport=httpx.MockTransport(handler),
                             headers=c._client.headers, follow_redirects=False)
    return c


def test_feed_is_pinned_to_iex():
    """Alpaca defaults to SIP, and this plan may not query recent SIP data.

    Omitting `feed` cost both ways. Any window reaching today came back 403 `subscription does not
    permit querying recent SIP data`, which is every scheduled top-up; and an older window came
    back 200 carrying CONSOLIDATED TAPE bars that were then stored under SOURCE
    'alpaca:iex:adjusted', making the provenance recorded on the row false.
    """
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.url.params)
        return httpx.Response(200, json={"bars": {"SPY": [{"c": 1.0}]}, "next_page_token": None})

    _client(handler).daily_batch(["SPY"], date(2026, 8, 15), date(2026, 9, 14))
    assert seen["feed"] == "iex"


def test_class_shares_go_out_dotted_and_come_back_hyphenated():
    """`GEF-B` is a 400 `invalid symbol` at Alpaca and takes its whole 100-symbol batch with it.

    The database stores the SEC/Nasdaq hyphen spelling, so the conversion has to happen at the
    wire and be undone before any row is written — a bar stored under 'GEF.B' would be a second,
    permanently stale symbol rather than an update to the real one.
    """
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.url.params)
        return httpx.Response(200, json={"bars": {"GEF.B": [{"c": 110.5}], "AAPL": [{"c": 324.9}]},
                                         "next_page_token": None})

    out = _client(handler).daily_batch(["GEF-B", "AAPL"], date(2026, 8, 15), date(2026, 9, 14))
    assert seen["symbols"] == "GEF.B,AAPL"          # the wire never sees a hyphen
    assert set(out) == {"GEF-B", "AAPL"}            # the caller never sees a dot


def test_pagination_merges_every_page():
    """`limit` counts bars ACROSS symbols, not per symbol, so a full batch routinely truncates
    mid-symbol. Stopping at page one would drop whole symbols silently — and because SPY is
    requested first on purpose, the dropped one can be the benchmark that unscoreables the rest."""
    pages = [
        {"bars": {"SPY": [{"c": 1.0}]}, "next_page_token": "tok"},
        {"bars": {"SPY": [{"c": 2.0}], "AAPL": [{"c": 3.0}]}, "next_page_token": None},
    ]
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.params.get("page_token"))
        return httpx.Response(200, json=pages[len(calls) - 1])

    out = _client(handler).daily_batch(["SPY", "AAPL"], date(2026, 8, 15), date(2026, 9, 14))
    assert calls == [None, "tok"]
    assert [b["c"] for b in out["SPY"]] == [1.0, 2.0]
    assert [b["c"] for b in out["AAPL"]] == [3.0]


def test_both_credential_halves_are_required():
    """A key id with no secret reaches Alpaca as an anonymous request and 403s on every bar, which
    reads like an outage. Refuse at construction instead."""
    with pytest.raises(ValueError):
        AlpacaClient("key-id", "")
