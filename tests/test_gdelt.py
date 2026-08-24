"""Offline tests for the GDELT adapter's parsing and mapping.

Fixtures are real article records captured from the live API on 2026-07-25, before an unpaced
burst of probe requests got this IP rate-limited (which is itself the reason the adapter paces
itself — see MIN_INTERVAL_S). No network here.
"""
import httpx
import pytest

from tradeos.ingestion import gdelt

# Verbatim from the live API.
REAL_ARTICLES = [
    {"url": "https://news.cnfol.com/guoneicaijing/20260725/31234567.shtml",
     "url_mobile": "", "title": "央行将7月末前后开展4次隔夜逆回购 对冲月底资金波动",
     "seendate": "20260725T023000Z", "socialimage": "", "domain": "news.cnfol.com",
     "language": "Chinese", "sourcecountry": "China"},
    {"url": "https://www.stcn.com/article/detail/9876543.html",
     "title": "央行将在7月末8月初开展多次隔夜逆回购操作",
     "seendate": "20260724T121500Z", "domain": "stcn.com",
     "language": "Chinese", "sourcecountry": "China"},
]


# ------------------------------------------------------------------ timestamps

def test_parse_seendate_reads_gdelts_compact_format():
    dt = gdelt.parse_seendate("20260725T023000Z")
    assert (dt.year, dt.month, dt.day, dt.hour, dt.minute) == (2026, 7, 25, 2, 30)
    assert dt.tzinfo is not None                      # must be aware; it becomes knowable_time


@pytest.mark.parametrize("bad", [None, "", "not-a-date", "20260725", "20261325T023000Z"])
def test_parse_seendate_returns_none_rather_than_guessing(bad):
    assert gdelt.parse_seendate(bad) is None


# ------------------------------------------------------------------ country + language mapping

def test_country_names_map_to_iso_codes():
    assert gdelt.country_code("United Arab Emirates") == "AE"
    assert gdelt.country_code("united states") == "US"
    assert gdelt.country_code("  China  ") == "CN"


def test_unmapped_country_is_dropped_not_guessed():
    """A wrong country code puts an event on the wrong part of the globe. Absent beats wrong."""
    assert gdelt.country_code("Ruritania") is None
    assert gdelt.country_code(None) is None
    assert gdelt.country_code("") is None


def test_language_names_map_to_iso_codes():
    assert gdelt.language_code("Chinese") == "zh"
    assert gdelt.language_code("English") == "en"
    assert gdelt.language_code("Klingon") is None


# ------------------------------------------------------------------ article -> event

def test_real_article_becomes_a_well_formed_event():
    ev = gdelt.to_event(REAL_ARTICLES[0], "monetary_policy")
    assert ev["source"] == "gdelt"
    assert ev["external_id"] == ev["source_url"] == REAL_ARTICLES[0]["url"]
    assert ev["language"] == "zh" and ev["geo"] == ["CN"]
    assert ev["category"] == "monetary_policy"
    assert ev["knowable_time"] == ev["published_at"] == gdelt.parse_seendate("20260725T023000Z")
    assert ev["raw_payload"] == REAL_ARTICLES[0]      # kept whole, so the engine can be rerun


def test_non_english_titles_survive_intact():
    """A US-markets product would drop these. The whole point of GDELT here is that it does not."""
    ev = gdelt.to_event(REAL_ARTICLES[1], "monetary_policy")
    assert ev["title"] == "央行将在7月末8月初开展多次隔夜逆回购操作"


@pytest.mark.parametrize("missing", ["url", "title", "seendate"])
def test_article_missing_an_essential_field_is_dropped(missing):
    """Never store a placeholder row — an event with no time or no source cannot be reasoned about."""
    article = {**REAL_ARTICLES[0], missing: ""}
    assert gdelt.to_event(article, "monetary_policy") is None


def test_article_with_no_mappable_country_still_becomes_an_event():
    """Unknown geography is not a reason to discard a real event; it just has no geo."""
    ev = gdelt.to_event({**REAL_ARTICLES[0], "sourcecountry": "Ruritania"}, "conflict")
    assert ev is not None and ev["geo"] == []


# ------------------------------------------------------------------ pacing

def test_queries_are_a_deliberate_quota_budget():
    """Each query is one paced request, so this list IS the per-pass cost. Keep it short."""
    assert 1 <= len(gdelt.QUERIES) <= 8
    for category, query in gdelt.QUERIES:
        assert query.strip()
        assert category in __import__("tradeos.spine", fromlist=["spine"]).CATEGORIES


def test_minimum_interval_respects_the_measured_limit():
    """Measured 2026-07-25: three rapid requests earned a 429 that outlasted an hour."""
    assert gdelt.MIN_INTERVAL_S >= 5.0


# ------------------------------------------------------------------ backoff discipline

def test_backoff_is_long_enough_to_be_a_real_pause():
    """Measured: GDELT's penalty outlasts an hour. Retrying on the next scheduler tick would just
    re-earn it, which is how a free source gets lost permanently."""
    assert gdelt.BACKOFF_HOURS >= 1


def test_the_user_agent_is_honest_and_constant():
    """Rotating the User-Agent WOULD restore access after a 429 — GDELT's throttle is keyed on it.
    We deliberately do not: that is evasion of a rate limit on a free service, and it breaks the
    moment they tighten the check. The identifier must name this product and stay put."""
    ua = gdelt.UA["User-Agent"]
    assert "Rhumb" in ua
    assert not any(b in ua for b in ("Mozilla", "Chrome", "Safari", "AppleWebKit")), \
        "the User-Agent must not impersonate a browser"


def test_the_reason_for_not_rotating_is_written_down():
    """A future maintainer hitting a 429 will reach for a new UA string. The module must explain
    why that is the wrong fix, or the reasoning is lost the first time someone is in a hurry."""
    import inspect
    src = inspect.getsource(gdelt)
    assert "evasion" in src.lower()


# ------------------------------------------------------------------ recognising a refusal
#
# GDELT says no in two shapes, and only one of them was recognised. 89 of this source's 118 calls
# recorded as `status = 0` — the generic exception branch — because a refusal delivered under
# HTTP 200 with no content-type hit the non-JSON check and raised ValueError. `_in_backoff` looks
# for 429, so the MOST COMMON refusal was invisible to it and the scheduler kept knocking.

# Measured live on 2026-08-24: HTTP 429, no content-type header, 444 bytes of plain text.
REFUSAL_BODY = (
    "Please limit requests to one every 5 seconds or contact support@example.invalid for larger "
    "queries. All high-traffic users should switch to our ngrams dataset: "
    "https://blog.gdeltproject.org/using-the-new-web-ngrams-dataset-to-find-relevant-coverage/.")


class _Resp:
    def __init__(self, status, body, content_type=None):
        self.status_code, self.text, self.headers = status, body, {}
        if content_type:
            self.headers["content-type"] = content_type

    def json(self):
        import json
        return json.loads(self.text)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=None, response=self)


class _Client:
    def __init__(self, resp):
        self._resp = resp

    def get(self, *_a, **_kw):
        return self._resp


@pytest.mark.parametrize("status", [429, 200])
def test_a_volume_refusal_is_recognised_under_either_status(status, monkeypatch):
    """The 200-shaped refusal is the one that recorded as an unknown fault for a month."""
    monkeypatch.setattr(gdelt, "_last_call", 0.0)
    monkeypatch.setattr(gdelt, "MIN_INTERVAL_S", 0.0)
    with pytest.raises(gdelt.RateLimited):
        gdelt._fetch(_Client(_Resp(status, REFUSAL_BODY)), "q", "2h", 10)


def test_a_malformed_query_is_still_an_ordinary_error_not_a_refusal(monkeypatch):
    """GDELT answers a bad query with HTML and a 200. That must NOT trigger a six-hour penalty —
    backing off from our own syntax error would hide the bug and cost the source for the day."""
    monkeypatch.setattr(gdelt, "MIN_INTERVAL_S", 0.0)
    with pytest.raises(ValueError):
        gdelt._fetch(_Client(_Resp(200, "<html>no</html>", "text/html")), "q", "2h", 10)


def test_a_good_response_still_parses(monkeypatch):
    monkeypatch.setattr(gdelt, "MIN_INTERVAL_S", 0.0)
    body = '{"articles": [{"url": "u", "title": "t", "seendate": "20260725T023000Z"}]}'
    got = gdelt._fetch(_Client(_Resp(200, body, "application/json")), "q", "2h", 10)
    assert len(got) == 1 and got[0]["title"] == "t"


def test_a_refusal_is_recorded_as_429_so_the_backoff_can_see_it(monkeypatch):
    """The whole point. `_in_backoff` reads `status = 429`; if a refusal records as 0 the penalty
    clock never starts, which is how 55 calls were made across two days with zero successes."""
    monkeypatch.setattr(gdelt, "MIN_INTERVAL_S", 0.0)
    monkeypatch.setattr(gdelt, "_in_backoff", lambda _c: (0.0, ""))
    monkeypatch.setattr(gdelt, "_next_start", lambda _c, _q: 0)
    monkeypatch.setattr(gdelt.httpx, "Client", lambda **_kw: _CtxClient(_Resp(200, REFUSAL_BODY)))
    recorded = []
    monkeypatch.setattr(gdelt, "_record_call",
                        lambda _c, status, _ms, ok, category="": recorded.append((status, ok,
                                                                                  category)))
    out = gdelt.ingest(_Conn(), queries=[("trade_policy", "q")])
    assert out["rate_limited"] is True
    assert recorded == [(429, False, "trade_policy")]


class _CtxClient(_Client):
    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


# ------------------------------------------------------------------ starvation
#
# `trade_policy` sat fifth in a list a refusal truncates after one or two requests, so it had NEVER
# executed. GDELT's whole contribution was 142 conflict + 142 monetary_policy events and nothing
# else, ever — the two queries at positions one and two.

class _Cur:
    """One cursor, many statements — which is how `_in_backoff` actually uses it. `results` is a
    list of row-sets, consumed in execute order; a single row-set is reused for every statement."""
    def __init__(self, results):
        self._results = list(results)
        self._rows: list = []
        self.executed: list = []

    def execute(self, sql, params=()):
        self.executed.append((sql, params))
        self._rows = self._results.pop(0) if len(self._results) > 1 else (self._results or [[]])[0]

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


class _Conn:
    def __init__(self, *results):
        self._results = list(results) or [[]]
        self.cur = None

    def cursor(self):
        self.cur = _Cur(self._results)
        return self.cur

    def commit(self):
        pass


def test_the_pass_starts_with_a_query_that_has_never_been_attempted():
    """A query with no call history sorts ahead of every query that has one, so a never-run query
    goes first on the very next pass rather than waiting for a rotation to reach it."""
    from datetime import UTC, datetime
    path = "/api/v2/doc/doc"
    now = datetime(2026, 8, 24, tzinfo=UTC)
    conn = _Conn([(f"{path} monetary_policy", now), (f"{path} conflict", now)])
    i = gdelt._next_start(conn, list(gdelt.QUERIES))
    assert gdelt.QUERIES[i][0] not in ("monetary_policy", "conflict")


def test_the_pass_starts_with_the_least_recently_attempted_query():
    from datetime import UTC, datetime, timedelta
    path = "/api/v2/doc/doc"
    now = datetime(2026, 8, 24, tzinfo=UTC)
    rows = [(f"{path} {cat}", now - timedelta(hours=n))
            for n, (cat, _q) in enumerate(gdelt.QUERIES)]
    conn = _Conn(rows)
    i = gdelt._next_start(conn, list(gdelt.QUERIES))
    assert gdelt.QUERIES[i][0] == gdelt.QUERIES[-1][0], "the oldest attempt must go first"


def test_rotation_reaches_every_query_even_when_each_pass_dies_after_one_request():
    """The regression test for the actual bug: with a fixed order and a pass that dies on request
    one, positions two onward are unreachable forever. Rotation must cover all five."""
    from datetime import UTC, datetime, timedelta
    path = "/api/v2/doc/doc"
    clock = datetime(2026, 8, 24, tzinfo=UTC)
    history: dict[str, datetime] = {}
    started = []
    for _pass in range(len(gdelt.QUERIES) * 2):
        conn = _Conn([(f"{path} {c}", t) for c, t in history.items()])
        i = gdelt._next_start(conn, list(gdelt.QUERIES))
        cat = gdelt.QUERIES[i][0]
        started.append(cat)
        clock += timedelta(hours=1)
        history[cat] = clock                       # one request, then the pass dies
    assert set(started) == {c for c, _ in gdelt.QUERIES}, f"starved: {started}"


# ------------------------------------------------------------------ backoff sees both signals

NO_429 = [(None,)]                                  # the 429 lookup finds nothing


def test_backoff_engages_after_a_recent_429():
    conn = _Conn([(1.0,)])                          # one hour since the last 429
    remaining, why = gdelt._in_backoff(conn)
    assert remaining == pytest.approx(gdelt.BACKOFF_HOURS - 1.0)
    assert "rate limited" in why


def test_an_old_429_no_longer_holds_the_source_shut():
    conn = _Conn([(gdelt.BACKOFF_HOURS + 1,)], [(False, 99.0, 1)])
    assert gdelt._in_backoff(conn) == (0.0, "")


def test_backoff_engages_on_a_run_of_unattributed_failures():
    """75% of this source's failures recorded as status 0 and the backoff never engaged: 30 calls
    in one day, zero successes, no pause. A run of failures is reason enough to wait."""
    conn = _Conn(NO_429, [(True, 0.1, gdelt.CONSECUTIVE_FAILURES)])
    remaining, why = gdelt._in_backoff(conn)
    assert remaining > 0
    assert "consecutive failures" in why


def test_a_run_of_failures_that_includes_a_success_does_not_back_off():
    """One flaky call must not silence the source; `bool_and` is what encodes that."""
    conn = _Conn(NO_429, [(False, 0.1, gdelt.CONSECUTIVE_FAILURES)])
    assert gdelt._in_backoff(conn) == (0.0, "")


def test_too_few_calls_to_be_a_run_does_not_back_off():
    """A brand-new install with two failed calls is not a penalised source."""
    conn = _Conn(NO_429, [(True, 0.1, gdelt.CONSECUTIVE_FAILURES - 1)])
    assert gdelt._in_backoff(conn) == (0.0, "")


def test_the_unknown_fault_pause_is_shorter_than_the_stated_penalty():
    """A 429 is GDELT telling us the rule. A run of unattributed failures is a guess, so it must
    not cost the same six hours — recovery from a blip should be quick."""
    assert 0 < gdelt.UNKNOWN_FAULT_BACKOFF_HOURS < gdelt.BACKOFF_HOURS


def test_the_call_log_records_which_query_ran():
    """`source_calls` could say a gdelt call failed but not WHICH — which is precisely why nobody
    noticed three of five queries had never run. Never the query string, though: that is the
    credential-leak rule in scheduler.redact()."""
    captured = {}

    class _RecCur(_Cur):
        def execute(self, sql, params=()):
            captured["params"] = params

    class _RecConn(_Conn):
        def cursor(self):
            return _RecCur([])

    gdelt._record_call(_RecConn(), 200, 12, True, "trade_policy")
    endpoint = captured["params"][0]
    assert endpoint.endswith(" trade_policy")
    assert "sourcelang" not in endpoint and "?" not in endpoint
