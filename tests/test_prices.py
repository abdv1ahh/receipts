"""Offline tests for EOD price ingestion.

Two of these exist because of what the free Tiingo tier actually does, measured 2026-08-24 against
the live key: the hourly ceiling is roughly 57 unique symbols, and once it is reached every
remaining symbol in the pass 429s as well. A pass that ignores that spends its quota proving it is
rate limited instead of fetching prices.
"""
from datetime import date

import httpx
import pytest

from tradeos.ingestion import prices


class _Cur:
    def execute(self, *_a, **_kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


class _Conn:
    def cursor(self):
        return _Cur()

    def commit(self):
        pass


class _Client:
    """Answers per symbol from a script: an Exception is raised, a list is returned."""

    def __init__(self, script):
        self.script = script
        self.asked: list[str] = []

    def daily(self, ticker, _start, _end):
        self.asked.append(ticker)
        answer = self.script.get(ticker.upper(), None)
        if isinstance(answer, Exception):
            raise answer
        return answer


def _rate_limited():
    return RuntimeError("Client error '429 Too Many Requests' for url 'https://api.tiingo.com/x'")


def test_a_run_of_rate_limits_stops_the_pass():
    """The quota-preserving rule. Without it a 400-symbol pass makes 400 requests to store nothing."""
    symbols = [f"SYM{i}" for i in range(20)]
    client = _Client({s: _rate_limited() for s in symbols})
    out = prices.ingest_prices(_Conn(), client, symbols, date(2026, 7, 20))
    assert out["rate_limited"] is True
    assert len(client.asked) == prices.CONSECUTIVE_RATE_LIMITS, \
        "the pass must stop at the threshold, not walk the whole list"


def test_an_isolated_rate_limit_does_not_stop_the_pass():
    """A single 429 between successes is a blip, not a ceiling; the counter has to reset."""
    row = [{"date": "2026-08-20", "adjOpen": 1.0, "adjHigh": 2.0, "adjLow": 0.5,
            "adjClose": 1.5, "adjVolume": 10}]
    symbols = ["A", "B", "C", "D", "E"]
    client = _Client({"A": row, "B": _rate_limited(), "C": row, "D": _rate_limited(), "E": row})
    out = prices.ingest_prices(_Conn(), client, symbols, date(2026, 7, 20))
    assert out["rate_limited"] is False
    assert client.asked == symbols
    assert out["with_data"] == 3 and out["rejected"] == 2


def test_an_ordinary_failure_does_not_count_toward_the_rate_limit_run():
    """Only a 429 means "the ceiling"; a parse error on three bad symbols must not silence the run."""
    symbols = ["A", "B", "C", "D"]
    client = _Client({s: ValueError("malformed payload") for s in symbols})
    out = prices.ingest_prices(_Conn(), client, symbols, date(2026, 7, 20))
    assert out["rate_limited"] is False
    assert client.asked == symbols and out["rejected"] == 4


@pytest.mark.parametrize("bad", [
    {"date": "2026-08-20", "adjClose": None},                       # no close
    {"date": "2026-08-20", "adjClose": 0},                          # non-positive close
    {"date": "2026-08-20", "adjClose": 1.0, "adjHigh": 1.0, "adjLow": 5.0},   # high < low
    {"adjClose": 1.0},                                              # no date
])
def test_an_unusable_row_is_dropped_rather_than_stored(bad):
    assert prices._valid_row(bad, date(2026, 8, 24)) is None


def test_a_future_dated_row_is_dropped():
    """Point-in-time discipline: a price dated after today would let a backtest see the future."""
    row = {"date": "2027-01-04", "adjClose": 1.0}
    assert prices._valid_row(row, date(2026, 8, 24)) is None


# ------------------------------------------------------- the credential never reaches the URL

def _mock(client: prices.TiingoClient, handler) -> prices.TiingoClient:
    """Swap the transport UNDER the real client, so the headers, params and URL under test are the
    ones `TiingoClient.__init__` actually built rather than a re-creation of them."""
    client._client._transport = httpx.MockTransport(handler)
    return client


def test_the_credential_is_sent_as_a_header_not_in_the_query_string():
    """B-30 was `?token=`: httpx puts the full request URL in its exception text, `reject()` stores
    that text, and so the live key sat in 1,172 `ingest_rejects` rows for five weeks. Tiingo accepts
    both forms, so this is a free fix — but only while nobody puts the token back in `params`."""
    seen = {}

    def _capture(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json=[{"date": "2026-08-20", "adjClose": 1.0}])

    client = _mock(prices.TiingoClient("LIVEKEY123"), _capture)
    client.daily("AAPL", date(2026, 7, 20), date(2026, 8, 21))

    assert seen["auth"] == "Token LIVEKEY123", "the token must authenticate the request"
    assert "LIVEKEY123" not in seen["url"] and "token=" not in seen["url"]
    assert "startDate=2026-07-20" in seen["url"], "the harmless params must survive the move"


def test_a_failed_request_carries_no_credential_even_with_redaction_out_of_the_path():
    """The point of B-30's second half: redaction must stop being load-bearing. `reject()` is
    replaced here rather than mocked around it, so nothing redacts anything — and the reason text
    still has to be clean, because there is no longer a credential in the URL to remove."""
    captured = {}

    def _unredacting_reject(_conn, _source, _accession, reason, counters):
        counters["rejected"] += 1
        captured["reason"] = reason

    client = _mock(prices.TiingoClient("LIVEKEY123"),
                   lambda _r: httpx.Response(500, text="Tiingo is having a day"))
    original, prices.reject = prices.reject, _unredacting_reject
    try:
        out = prices.ingest_prices(_Conn(), client, ["AAPL"], date(2026, 7, 20))
    finally:
        prices.reject = original

    assert out["rejected"] == 1
    assert "LIVEKEY123" not in captured["reason"] and "token=" not in captured["reason"]
    assert "500" in captured["reason"] and "api.tiingo.com" in captured["reason"], \
        "the reject must still be diagnosable — host and status are why the row is kept"


def test_redirects_stay_off_so_a_header_credential_cannot_be_handed_to_another_host():
    """A query-string token only ever went where the URL pointed. A header set on the client is
    attached to whatever host a redirect lands on, and `daily()`'s allowlist only checks the URL we
    build — so following redirects here would hand Tiingo's key to the redirect target."""
    assert prices.TiingoClient("k")._client.follow_redirects is False
