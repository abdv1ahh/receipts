"""The price command names, pinned.

Alpaca became the default price source on 2026-09-14. That promotion is a routing decision spread
across three command names, and nothing else in the suite would notice if it silently reverted:
`ingest-prices` running Tiingo again would not fail a test, it would just quietly go back to a
source that cannot finish a pass over the cluster universe (~50 requests/hour, one symbol per
request, measured alphabetical staleness bias — CLAUDE.md §0h).

`main()` parses and dispatches in one function, so these drive the REAL parser through sys.argv
and stub only the command bodies. Nothing here touches the network or the database.
"""
from __future__ import annotations

import pytest

from tradeos import cli


def _dispatch(monkeypatch, argv: list[str]) -> str:
    """Run the real parser over argv; return which command function it reached."""
    called: list[str] = []
    for name in ("cmd_ingest_prices", "cmd_ingest_prices_alpaca"):
        monkeypatch.setattr(cli, name, (lambda n: lambda _args: called.append(n))(name))
    monkeypatch.setattr("sys.argv", ["tradeos", *argv])
    cli.main()
    return called[0]


def test_ingest_prices_runs_alpaca(monkeypatch):
    """The bare, muscle-memory command must reach the source that can actually finish."""
    assert _dispatch(monkeypatch, ["ingest-prices", "--symbols", "SPY"]) == "cmd_ingest_prices_alpaca"


def test_alpaca_alias_still_resolves(monkeypatch):
    """Kept deliberately: the Makefile, GO-LIVE.md and three docs name one spelling or the other,
    and a command that silently stops existing is worse than a second spelling."""
    assert _dispatch(monkeypatch, ["ingest-prices-alpaca", "--symbols", "SPY"]) == "cmd_ingest_prices_alpaca"


def test_tiingo_is_still_reachable_as_the_fallback(monkeypatch):
    """Tiingo is the only second opinion this database has on a price, and `compare-prices`
    measures Alpaca against the rows it wrote. Demoted, never removed."""
    assert _dispatch(monkeypatch, ["ingest-prices-tiingo", "--symbols", "SPY"]) == "cmd_ingest_prices"


@pytest.mark.parametrize("flag", ["--only-stale", "--symbols-from-clusters",
                                  "--only-missing", "--only-missing-history"])
def test_the_selector_flags_survived_the_promotion(monkeypatch, flag):
    """`--only-stale` is the flag that put SPY first and ended the alphabetical bias. Losing a
    selector in a rename would be invisible until a pass quietly fetched the wrong symbols."""
    assert _dispatch(monkeypatch, ["ingest-prices", flag]) == "cmd_ingest_prices_alpaca"
