"""Every command this CLI registers exists, is reachable, and answers `--help`.

WHY THIS FILE EXISTS, precisely. `cli.main()` is a flat run of `sub.add_parser(...)` followed by
`.set_defaults(fn=...)`, and it was broken twice in one session by deletions that began on the
right line and ended inside the next command's flags. argparse accepts that silently: the parser
still builds, the command still registers, `--help` still prints, and a flag belonging to one
command has quietly moved to another. Nothing in the suite noticed either time, because nothing in
the suite had ever invoked the parser.

So this walks the built parser rather than reading the source. Three properties, and the third is
the one the accident needed:

  REGISTERED   every command in EXPECTED is present, and nothing is present that is not in
               EXPECTED. A command deleted by accident and a command left behind by accident are
               the same bug seen from two sides.
  DISPATCHES   every subparser has an `fn`. `set_defaults(fn=...)` is a separate statement from
               `add_parser`, so a cut between them leaves a command that parses and then crashes
               with AttributeError at the moment somebody runs it.
  ANSWERS      every command answers `--help` without raising. argparse builds help text lazily
               from the accumulated actions, so a malformed argument spec survives registration
               and fails here, which is the first place a human would meet it.

Offline and importing only `cli`: no database, no network, and `--help` exits before any command
body runs.
"""
from __future__ import annotations

import argparse
import contextlib
import io

import pytest

from tradeos import cli

# The whole surface, written out rather than derived, so a command appearing or disappearing shows
# up as a diff in this list and has to be argued for in a commit message.
EXPECTED = {
    "migrate",
    "ingest-prices", "ingest-prices-alpaca",     # the alias is deliberate; see cli.main
    "check-source",
    "scheduler",
    "seed-admin", "seed-demo", "seed-house-records", "create-invites",
    "resolve-calls", "verify-chain",
    # Writes every sealed chain to a directory that verifies with no server and no database. The
    # record has to outlive the instance, or it is a record with an expiry date.
    "export-records",
    "status", "preflight",
}


def _subparsers() -> dict[str, argparse.ArgumentParser]:
    parser = cli.build_parser() if hasattr(cli, "build_parser") else None
    if parser is None:
        # `main()` parses argv and dispatches, so it cannot be called to obtain the parser. Build
        # it the same way argparse does internally: run main() with a sentinel that makes
        # parse_args raise after the parser is fully constructed.
        parser = _parser_from_main()
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return dict(action.choices)
    raise AssertionError("cli.main() registered no subparsers")


def _parser_from_main() -> argparse.ArgumentParser:
    """The parser `main()` builds, captured without running a command.

    `main()` ends in `parse_args()` then `args.fn(args)`. Passing `--help` makes argparse print and
    raise SystemExit before `fn` is reached, and the parser it built is the one that printed — so
    it is captured on the way past rather than reconstructed here, which would be a second copy of
    the thing under test.
    """
    captured = {}
    real_init = argparse.ArgumentParser.__init__

    def spy(self, *a, **kw):
        real_init(self, *a, **kw)
        if kw.get("prog") == "tradeos" or (a and a[0] == "tradeos"):
            captured["parser"] = self

    argparse.ArgumentParser.__init__ = spy
    try:
        with contextlib.redirect_stdout(io.StringIO()), pytest.raises(SystemExit):
            cli.main.__wrapped__(["--help"]) if hasattr(cli.main, "__wrapped__") else _run_help()
    finally:
        argparse.ArgumentParser.__init__ = real_init
    assert "parser" in captured, "could not capture the parser cli.main() builds"
    return captured["parser"]


def _run_help() -> None:
    import sys
    argv = sys.argv
    sys.argv = ["tradeos", "--help"]
    try:
        cli.main()
    finally:
        sys.argv = argv


def test_exactly_the_expected_commands_are_registered():
    """Both directions. A command deleted by accident and one left behind by accident are the same
    bug: the CLI no longer says what the product does."""
    registered = set(_subparsers())
    assert registered == EXPECTED, (
        f"missing: {sorted(EXPECTED - registered)}; unexpected: {sorted(registered - EXPECTED)}")


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_every_command_dispatches_to_a_function(name):
    """`set_defaults(fn=...)` is a SEPARATE statement from `add_parser`, so a cut landing between
    the two leaves a command that parses cleanly and then raises AttributeError the moment somebody
    runs it. That is exactly the shape of the accident this file exists for."""
    sub = _subparsers()[name]
    fn = sub.get_default("fn")
    assert callable(fn), f"{name} registers no fn; it would crash on first use"


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_every_command_answers_help(name):
    """argparse builds help text lazily from the accumulated actions, so a malformed argument spec
    survives registration and fails here — which is the first place a human would meet it."""
    sub = _subparsers()[name]
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        text = sub.format_help()
    assert text.strip(), f"{name} --help printed nothing"


def test_no_two_commands_share_a_dispatch_target_by_accident():
    """The alias is the one legitimate case, and it is named here so a SECOND accidental collision
    cannot hide behind it: `ingest-prices-alpaca` is kept because the Makefile and three documents
    name one spelling or the other, and a command that silently stops existing is worse than two
    spellings of one."""
    subs = _subparsers()
    by_fn: dict[object, list[str]] = {}
    for name, sub in subs.items():
        by_fn.setdefault(sub.get_default("fn"), []).append(name)
    shared = {tuple(sorted(v)) for v in by_fn.values() if len(v) > 1}
    assert shared == {("ingest-prices", "ingest-prices-alpaca")}, shared
