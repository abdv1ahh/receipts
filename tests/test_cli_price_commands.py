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
    monkeypatch.setattr(cli, "cmd_ingest_prices_alpaca",
                        lambda _args: called.append("cmd_ingest_prices_alpaca"))
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


def test_tiingo_is_gone_from_the_product(monkeypatch):
    """Removed, not demoted, and the reason is licensing rather than performance.

    Tiingo's terms permit persistent storage only on eligible paid plans, with deletion obligations
    when the subscription ends. This application stores every entry and exit price permanently and
    displays the arithmetic on a public page, which is exactly what those terms do not grant on a
    free key — so shipping Tiingo as a fallback in a public repository would hand every self-hoster
    a breach they never opted into. The adapter, its commands and `compare-prices` live on in the
    `research_platform` tag, where the measurement that justified the migration was taken.
    """
    for gone in ("ingest-prices-tiingo", "compare-prices"):
        monkeypatch.setattr("sys.argv", ["tradeos", gone, "--symbols", "SPY"])
        with pytest.raises(SystemExit) as exc:
            cli.main()
        assert exc.value.code != 0, f"{gone} still parses"


def test_alpaca_is_the_only_price_source_left():
    """Asserted against the package, not the parser: a second adapter that nothing routes to is
    still a second adapter a self-hoster can find and wire up."""
    import pathlib as _p
    root = _p.Path(__file__).resolve().parents[1] / "tradeos" / "ingestion"
    adapters = sorted(f.name for f in root.glob("prices*.py"))
    assert adapters == ["prices_alpaca.py"], adapters


@pytest.mark.parametrize("flag", ["--only-stale", "--symbols-from-clusters",
                                  "--only-missing", "--only-missing-history"])
def test_the_selector_flags_survived_the_promotion(monkeypatch, flag):
    """`--only-stale` is the flag that put SPY first and ended the alphabetical bias. Losing a
    selector in a rename would be invisible until a pass quietly fetched the wrong symbols."""
    assert _dispatch(monkeypatch, ["ingest-prices", flag]) == "cmd_ingest_prices_alpaca"
