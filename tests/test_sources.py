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

def test_no_watchlist_route_accepts_an_owner_as_a_parameter():
    """B-22: /api/watchlist took the owner as a QUERY PARAMETER defaulting to 'demo', with no
    session check — every account shared one list and any caller could address another's by
    changing one parameter. The owner must come from the session and nowhere else."""
    import inspect
    import re

    from tradeos import app as app_module

    src = inspect.getsource(app_module)
    for match in re.finditer(r"^def (watchlist_\w+)\((.*?)\)\s*->", src, re.M | re.S):
        name, params = match.group(1), match.group(2)
        assert "user:" not in params, f"{name} takes the owner as a parameter"
        assert "user_key" not in params, f"{name} takes a raw key as a parameter"
        assert "tos_session" in params, f"{name} does not read the session"


def test_watchlist_queries_are_scoped_by_user_id():
    """A query filtering on the old free-text key would silently reintroduce the shared pile."""
    import inspect

    from tradeos import app as app_module

    src = inspect.getsource(app_module)
    for line in src.splitlines():
        if "FROM watchlists" in line or "INTO watchlists" in line:
            assert "user_key" not in line, f"watchlist query still uses user_key: {line.strip()}"


def test_httpx_request_logging_cannot_print_an_api_key():
    """httpx logs every request at INFO with the full URL, query string included. Tiingo
    authenticates with `?token=`, so that one logger turns a captured CLI session or a CI log into
    a credential disclosure. It leaked in exactly that way while backfilling price history by hand.

    scheduler.redact() covers what gets STORED; this covers what gets PRINTED."""
    import pathlib
    src = pathlib.Path(__file__).resolve().parents[1].joinpath("tradeos", "cli.py").read_text()
    assert 'logging.getLogger("httpx").setLevel(logging.WARNING)' in src, (
        "httpx INFO logging re-enabled — any ?token= or ?key= URL will print its credential")
