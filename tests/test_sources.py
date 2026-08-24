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


def _openfigi_probe_source() -> str:
    import pathlib
    src = pathlib.Path(__file__).resolve().parents[1].joinpath("tradeos", "cli.py").read_text()
    return src.split('if key == "openfigi":')[1].split('if key == "coingecko":')[0]


def test_openfigi_probe_cannot_pass_without_the_key_doing_work():
    """OpenFIGI's mapping endpoint answers KEYLESS requests too, so a 200 on an ordinary body
    proves nothing about the key — the same trap `/api/test` set for Tiingo. Measured
    2026-08-24: the keyless cap is 10 jobs per request and a key raises it to 100, so a body of
    ELEVEN separates the three states cleanly (valid 200 / invalid 401 / absent 413). A probe
    that drops back under 10 jobs would report OK for a key that is never applied."""
    probe = _openfigi_probe_source()
    assert "X-OPENFIGI-APIKEY" in probe, "the probe must actually send the key"
    # Count the CUSIPs the probe posts; it must stay over the keyless ceiling.
    listed = probe.split("cusips = [")[1].split("]")[0]
    jobs = len([c for c in listed.split(",") if c.strip()])
    assert jobs > 10, (
        f"probe posts {jobs} jobs — at or under the keyless cap of 10 it would also succeed "
        "with no key at all, so it would no longer test authentication"
    )
    assert "413" in probe, "a 413 means the key was not applied and must report FAILED, not OK"


def test_openfigi_probe_reports_failure_when_the_key_was_not_applied(monkeypatch):
    """413 is the signature of a request that was rated as keyless — the key never reached the
    process. That is precisely the misconfiguration this command exists to surface, so it must
    not raise_for_status into a generic 'request failed'."""
    import httpx

    from tradeos import cli

    class _Resp:
        status_code = 413

        def raise_for_status(self):
            raise AssertionError("413 must be handled before raise_for_status")

        def json(self):
            return []

    class _Client:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def post(self, *a, **k): return _Resp()

    monkeypatch.setenv("OPENFIGI_API_KEY", "irrelevant-to-this-test")
    monkeypatch.setattr(httpx, "Client", _Client)
    ok, detail = cli._probe("openfigi")
    assert ok is False, "a keyless-rated request must report FAILED"
    assert "not applied" in detail


def test_openfigi_client_never_puts_the_key_in_a_url():
    """B-30: httpx puts the full request URL in its exception text, so a credential carried in a
    query string lands in any stored error — that is how 1,172 ingest_rejects rows came to hold
    the live Tiingo key. OpenFIGI authenticates with a HEADER and must keep doing so."""
    import pathlib
    src = pathlib.Path(__file__).resolve().parents[1].joinpath(
        "tradeos", "resolution", "openfigi.py").read_text()
    assert 'headers["X-OPENFIGI-APIKEY"] = api_key' in src, (
        "the key must travel as a header, never in the URL"
    )
    assert "params=" not in src, "a params= dict would put the key in the query string"
    assert "str(exc)" not in src, (
        "raw httpx exception text carries the request URL; store the exception TYPE instead"
    )
