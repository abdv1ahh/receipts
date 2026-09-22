"""Tests for the source registry and the integration status surface.

Includes the fix for the finding this phase's own security review raised: /api/integrations was
unauthenticated and returned `str(exc)` from arbitrary ingestion failures, and httpx puts the full
request URL — query string included — into its exception messages. A keyed API's credential could
therefore reach the database and then the public internet."""
import argparse
import pathlib

import pytest

from tradeos import scheduler, sources


# ------------------------------------------------------------------ the registry
def test_alpaca_state_is_derived_from_config(monkeypatch):
    """Alpaca is the price source, so a wrong state here stops outcomes being scored at all."""
    monkeypatch.delenv("ALPACA_API_KEY_ID", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET_KEY", raising=False)
    assert sources.by_key("alpaca")["state"] == sources.NEEDS_KEY
    monkeypatch.setenv("ALPACA_API_KEY_ID", "id")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "secret")
    assert sources.by_key("alpaca")["state"] == sources.CONNECTED


def test_the_catalog_lists_every_source_and_nothing_more():
    """Both directions, because both have bitten. A source absent from the catalog is invisible to
    the operator no matter how badly it is failing — GDELT was exactly that for three phases. A
    source LISTED but no longer talked to is the opposite failure and the one this deletion could
    introduce: an integration page telling an operator to paste a Reddit key for a surface that no
    longer exists.

    Four entries, and each one is an external dependency the product still has: the price vendor,
    outbound mail, Google sign-in, and error reporting.
    """
    assert {s["key"] for s in sources.catalog()} == {"alpaca", "smtp", "google_oauth", "sentry"}


def test_alpaca_is_the_only_source_a_running_instance_actually_needs():
    """The other three are optional by construction and the product says so rather than failing:
    mail refuses to send unconfigured (docs/known_gaps.md §1), Google sign-in is config-gated
    beside ordinary email signup, and Sentry initialises to nothing. Alpaca is not optional — with
    no price series there is no universe to publish on and nothing can ever be scored."""
    alpaca = sources.by_key("alpaca")
    assert alpaca["jobs"] == ["ingest_prices"]
    assert set(alpaca["env"]) == {"ALPACA_API_KEY_ID", "ALPACA_API_SECRET_KEY"}
    for optional in ("smtp", "google_oauth", "sentry"):
        assert sources.by_key(optional)["jobs"] == [], f"{optional} claims a scheduler job"


def test_every_dynamic_source_has_a_config_check():
    """A catalog entry with `state: None` is asking for its state to be COMPUTED. If no _DYNAMIC
    entry answers, `_state` falls through to NEEDS_KEY forever: the source can never report
    connected however valid the credential, `check-source` refuses to run its probe, and the
    integration page tells the operator to add a key they already added. Alpaca shipped that way.
    This asserts the two tables cannot drift apart again."""
    dynamic = {s["key"] for s in sources.CATALOG if s["state"] is None}
    assert dynamic, "no dynamic sources found - has the registry's shape changed?"
    assert dynamic <= set(sources._DYNAMIC), (
        f"declared dynamic but no config check: {sorted(dynamic - set(sources._DYNAMIC))}")
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


def test_the_scheduler_and_the_ingesters_share_one_redactor():
    """Two copies of this would drift, and the copy that drifted would leak a key. `scheduler.redact`
    is the ingestion helper, not a second implementation of it."""
    from tradeos.ingestion import common
    assert scheduler.redact is common.redact


def test_reject_redacts_before_it_stores():
    """The leak this test exists for: httpx puts the whole request URL in its exception message,
    Tiingo authenticates with `?token=`, and five adapters hand raw exception text to `reject()`.
    1,172 rows in `ingest_rejects` held the live key in plain text back to 2026-07-16. Redaction
    happens inside `reject` so a sixth adapter cannot reintroduce it by forgetting."""
    from tradeos.ingestion.common import reject

    stored = {}

    class _Cur:
        def execute(self, _sql, params):
            stored["row"] = params

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    class _Conn:
        def cursor(self):
            return _Cur()

    counters = {"rejected": 0}
    raw = ("HTTPStatusError: Client error '429 Too Many Requests' for url "
           "'https://api.tiingo.com/tiingo/daily/aesi/prices?startDate=2026-07-20&token=LIVEKEY123'")
    reject(_Conn(), "prices", "AESI", raw, counters)

    _source, _accession, reason = stored["row"]
    assert "LIVEKEY123" not in reason and "token=" not in reason
    assert "429" in reason and "api.tiingo.com" in reason     # still diagnosable
    assert counters["rejected"] == 1


# ------------------------------------------------------------------ authorization, adversarially

def test_require_admin_contract_is_user_on_success_none_on_failure():
    """The guard returns the USER on success and None on failure. Every admin route must therefore
    branch on `not _require_admin(...)`.

    This exists because getting it backwards is silent: the route keeps working for the developer
    (who is an admin, and so is refused — obvious) OR keeps working for everyone (and the developer
    never notices). It happened while building Phase 2, and served an admin-only list to anonymous
    callers until an explicit check caught it."""
    import inspect
    import re

    from tradeos import app as app_module

    src = inspect.getsource(app_module)
    # Every call site must be one of the two safe shapes: assigned then negated, or negated inline.
    for line_no, line in enumerate(src.splitlines(), 1):
        if "_require_admin(" not in line or "def _require_admin" in line:
            continue
        assigned = re.search(r"(\w+)\s*=\s*_require_admin\(", line)
        negated_inline = "if not _require_admin(" in line
        assert assigned or negated_inline, (
            f"line {line_no}: _require_admin must be assigned-then-checked or negated inline, "
            f"got: {line.strip()}")
        if assigned:
            var = assigned.group(1)
            following = "\n".join(src.splitlines()[line_no:line_no + 3])
            assert f"if not {var}" in following, (
                f"line {line_no}: `{var} = _require_admin(...)` must be followed by `if not {var}`")


# ------------------------------------------------------------------ B-22: watchlist ownership
def test_httpx_request_logging_cannot_print_an_api_key():
    """httpx logs every request at INFO with the full URL, query string included. Tiingo
    authenticates with `?token=`, so that one logger turns a captured CLI session or a CI log into
    a credential disclosure. It leaked in exactly that way while backfilling price history by hand.

    scheduler.redact() covers what gets STORED; this covers what gets PRINTED."""
    import pathlib
    src = pathlib.Path(__file__).resolve().parents[1].joinpath("tradeos", "cli.py").read_text()
    assert 'logging.getLogger("httpx").setLevel(logging.WARNING)' in src, (
        "httpx INFO logging re-enabled — any ?token= or ?key= URL will print its credential")


def _tiingo_probe_source() -> str:
    import pathlib
    src = pathlib.Path(__file__).resolve().parents[1].joinpath("tradeos", "cli.py").read_text()
    return src.split('if key == "tiingo":')[1].split('if key == "coingecko":')[0]
def _openfigi_probe_source() -> str:
    import pathlib
    src = pathlib.Path(__file__).resolve().parents[1].joinpath("tradeos", "cli.py").read_text()
    return src.split('if key == "openfigi":')[1].split('if key == "coingecko":')[0]
def test_seed_demo_generates_its_password_rather_than_shipping_one():
    """The default used to be a constant that also appeared in CLAUDE.md, GO-LIVE.md and two
    runbooks — so every reader of the repository knew the login for a tier=pro account with no
    second factor, on every instance that had ever run the command. This is about to be a public
    repository, which turns that from untidy into a standing invitation."""
    import inspect

    from tradeos import cli

    src = inspect.getsource(cli.cmd_seed_demo)
    assert "secrets.token_hex" in src, "the demo password must be generated"
    assert "TradeOSDemo" not in src

    # And nowhere else in the tree either. The needle is assembled rather than written out, or
    # this file matches itself — which it did on the first run.
    needle = "TradeOS" + "Demo" + "2026"
    root = pathlib.Path(__file__).resolve().parents[1]
    hits = sorted(str(f.relative_to(root)) for f in root.rglob("*")
                  if f.is_file() and f.suffix in {".py", ".md", ".sh", ".yml", ".yaml"}
                  and ".git" not in f.parts and "node_modules" not in f.parts
                  and f.name != pathlib.Path(__file__).name
                  and needle in f.read_text(errors="ignore"))
    assert not hits, f"the old fixed demo password is still written down in {hits}"


def test_seed_demo_refuses_on_an_instance_serving_real_users(monkeypatch):
    """COOKIE_SECURE=true means session cookies go out over TLS, which means real users. A demo
    account is a permanent, fully privileged, MFA-less login; seeding one there has to be a
    decision rather than a habit."""
    from tradeos import cli

    monkeypatch.setenv("COOKIE_SECURE", "true")
    with pytest.raises(SystemExit) as exc:
        cli.cmd_seed_demo(argparse.Namespace(i_know=False))
    assert "--i-know" in str(exc.value)


def test_the_compose_file_ships_no_default_database_password():
    """A public repository that carries a literal `POSTGRES_PASSWORD` hands every self-hoster the
    same credential on a database whose port is published.

    Skips inside the API image, which mounts only `tests/`, `tradeos/` and `frontend/src` — the
    same reason `test_navigation.py` skips when the front end source is absent.
    """
    root = pathlib.Path(__file__).resolve().parents[1]
    if not (root / "docker-compose.yml").exists():
        pytest.skip("docker-compose.yml is not mounted here; this reads it from a checkout")
    compose = (root / "docker-compose.yml").read_text()
    assert "POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?" in compose, (
        "the password must be required, and `:?` rather than `:-` so an empty value is refused")
    assert "postgresql://tradeos:${POSTGRES_PASSWORD}@" not in compose
    assert (root / "scripts" / "setup.sh").exists(), "the quickstart needs a generator"
