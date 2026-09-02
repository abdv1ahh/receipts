"""The Receipts HTTP surface: what a stranger can reach, what needs a session, and the two rules
that must hold at the boundary rather than only in the modules behind it.

RULE ONE. The record, the board, the methodology, chain verification and the share card answer
WITHOUT a session. The product's argument is that a reader can check a caller without taking
anything on trust, and requiring an account with us would be the first thing taken on trust.

RULE TWO. A gated record never emits a percentage, anywhere, including on the share card. A card
is the part of this product that travels furthest from its own context, so it is the worst possible
place to print a rate the sample cannot support.

Skips cleanly with no database, like the other integrity tests.
"""
from __future__ import annotations

import pathlib
import re
import secrets

import pytest

try:
    from fastapi.testclient import TestClient

    from tradeos import db, presentation
    from tradeos.app import app
    from tradeos.receipts import calls as receipts_calls
    _IMPORTS_OK = True
except Exception:                                             # pragma: no cover
    _IMPORTS_OK = False


def _db_reachable() -> bool:
    if not _IMPORTS_OK:
        return False
    try:
        with db.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT to_regclass('calls')")
            return cur.fetchone()[0] is not None
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _db_reachable(),
                                reason="no database reachable; the Receipts API tests need one")

VALID = {"symbol": "ABT", "direction": "up", "horizon_days": 30, "confidence": "medium",
         "thesis": "a thesis with more than forty characters in it, so a reader can judge it"}


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def thin_caller():
    """A real caller with one real call: the gated case, which cannot be faked into existence."""
    handle = f"test-{secrets.token_hex(6)}"
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO callers (handle, display_name, kind, jurisdiction_attested)
                           VALUES (%s, 'Thin Record', 'human', true) RETURNING id""", (handle,))
            caller_id = cur.fetchone()[0]
        conn.commit()
        receipts_calls.publish(caller_id, VALID, conn)
        yield caller_id, handle
        with conn.cursor() as cur:
            cur.execute("ALTER TABLE calls DISABLE TRIGGER calls_append_only_trg")
            cur.execute("DELETE FROM calls WHERE caller_id = %s", (caller_id,))
            cur.execute("ALTER TABLE calls ENABLE TRIGGER calls_append_only_trg")
            cur.execute("DELETE FROM callers WHERE id = %s", (caller_id,))
        conn.commit()


# ------------------------------------------------------------------ the public boundary

@pytest.mark.parametrize("path", [
    "/api/board",
    "/api/receipts/methodology",
    "/api/receipts/convergence-v3",
    "/api/receipts/convergence-v3/verify",
    "/api/card/receipt/convergence-v3.svg",
    "/r/convergence-v3",
])
def test_the_public_surfaces_answer_without_a_session(client, path):
    assert client.get(path).status_code == 200


@pytest.mark.parametrize("method, path", [
    ("post", "/api/callers"),
    ("post", "/api/calls"),
    ("get", "/api/callers/me"),
    ("post", "/api/callers/verify/start"),
])
def test_writing_needs_a_session(client, method, path):
    kwargs = {"json": {}} if method == "post" else {}
    assert getattr(client, method)(path, **kwargs).status_code in (401, 422)


def test_the_admin_review_queue_is_admin_only(client):
    assert client.get("/api/admin/callers/pending").status_code == 401


def test_a_missing_handle_is_a_404_and_not_a_500(client):
    assert client.get("/api/receipts/nobody-holds-this").status_code == 404
    assert client.get("/api/receipts/nobody-holds-this/verify").status_code == 404
    assert client.get("/r/nobody-holds-this").status_code == 200      # a readable page, not an error


# ------------------------------------------------------------------ what the record says

def test_the_house_record_publishes_its_own_unflattering_numbers(client):
    """The engine was right 43.2% of the time on 412 resolved calls, which is below a coin flip,
    and its expectancy interval spans zero. If this test starts failing because the numbers moved,
    check the ledger before changing the test."""
    body = client.get("/api/board").json()
    house = body["house"]
    assert house["resolved_scoreable"] == 412
    assert house["hit_rate"] == 0.432
    assert house["hit_rate"] < 0.5                                  # below chance, and stays sayable
    assert house["expectancy_ci"][0] < 0 < house["expectancy_ci"][1]  # the interval spans zero
    assert house["expectancy_significant"] is False
    assert house["sample_needed_1pct"] == 1268
    assert house["sample_needed_1pct"] > house["resolved_scoreable"]


def test_the_board_carries_the_line_about_what_a_rank_means(client):
    body = client.get("/api/board").json()
    for phrase in ("not investment advice", "not a recommendation", "endorsement"):
        assert phrase in body["ranking_note"].lower() or phrase in body["disclaimer"].lower()


def test_every_public_receipts_payload_carries_the_disclaimer(client):
    for path in ("/api/board", "/api/receipts/methodology", "/api/receipts/convergence-v3"):
        assert "not investment advice" in client.get(path).json()["disclaimer"].lower()


def test_the_record_leads_with_misses(client):
    body = client.get("/api/receipts/convergence-v3").json()
    assert body["misses"], "a record with 167 misses must be able to show them"
    assert all(m["excess_return"] is not None for m in body["misses"])


def test_the_chain_verifies_over_the_whole_imported_record(client):
    body = client.get("/api/receipts/convergence-v3/verify").json()
    assert body["intact"] is True
    assert body["links"] == 323
    assert body["broken_at_seq"] is None


def test_verification_states_what_it_does_not_prove(client):
    """An investor who catches an overclaim discounts everything else, so the caveat travels with
    the result rather than living only on a page they might not open."""
    body = client.get("/api/receipts/convergence-v3/verify").json()
    assert "operator" in body["caveat"].lower()
    assert "blockchain" in body["caveat"].lower()


def test_the_methodology_is_read_from_the_code_not_typed_out(client):
    from tradeos.receipts import calls as calls_mod
    from tradeos.receipts import record, scoring
    body = client.get("/api/receipts/methodology").json()
    assert body["noise_floor"] == scoring.NOISE_FLOOR
    assert body["sample_gate"] == record.SAMPLE_GATE
    assert body["horizons"] == list(calls_mod.SCOREABLE_HORIZONS)
    assert body["universe"]["symbols"] > 0


# ------------------------------------------------------------------ the gate at the boundary

def test_a_gated_record_returns_no_rate_over_http(client, thin_caller):
    _caller_id, handle = thin_caller
    summary = client.get(f"/api/receipts/{handle}").json()["summary"]
    assert summary["gated"] is True
    assert summary["hit_rate"] is None and summary["expectancy"] is None
    assert summary["gate_reason"]


def test_a_gated_share_card_shows_low_n_and_never_a_percentage(client, thin_caller):
    _caller_id, handle = thin_caller
    svg = client.get(f"/api/card/receipt/{handle}.svg").text
    assert "LOW N" in svg
    assert not re.search(r"\d+\.\d%", svg), "a gated card must never print a rate"


def test_a_gated_share_page_says_why_rather_than_showing_a_rate(client, thin_caller):
    _caller_id, handle = thin_caller
    html = client.get(f"/r/{handle}").text
    assert "rate is not shown" in html
    assert not re.search(r"\d+\.\d% right", html)


def test_an_ungated_card_shows_the_rate_and_the_chain(client):
    svg = client.get("/api/card/receipt/convergence-v3.svg").text
    assert "40.8%" in svg
    assert "323 sealed calls" in svg
    assert "Past performance does not predict future results" in svg


# ------------------------------------------------------------------ the card, as a pure function

def test_the_card_refuses_a_rate_whenever_one_was_withheld_upstream():
    """`record.summary` returns None for a gated hit rate, and that None is the only signal the
    card needs. Asserted directly so a future caller cannot pass a rate around the gate."""
    svg = presentation.receipt_card_svg(
        handle="someone", display_name="Someone", counts={"hit": 3, "miss": 2, "inconclusive": 1,
                                                          "unscoreable": 0, "open": 4},
        hit_rate=None, hit_rate_ci=None, resolved_scoreable=5, links=10, brand="Rhumb")
    assert "LOW N" in svg and "%" not in svg
    assert ">3<" in svg and ">2<" in svg                      # the counts are still shown


def test_the_card_escapes_what_a_caller_typed():
    svg = presentation.receipt_card_svg(
        handle="a&b", display_name="<script>alert(1)</script>",
        counts={"hit": 0, "miss": 0, "inconclusive": 0, "unscoreable": 0, "open": 0},
        hit_rate=None, hit_rate_ci=None, resolved_scoreable=0, links=0, brand="Rhumb")
    assert "<script>" not in svg
    assert "&amp;" in svg and "&lt;script&gt;" in svg


def test_no_card_carries_the_pre_rebrand_name():
    """The share card is the most public string in the product: the image a shared link renders in
    every feed. It had the old name welded in as markup for eight phases."""
    for svg in (presentation.receipt_card_svg(
                    handle="h", display_name="D",
                    counts={"hit": 0, "miss": 0, "inconclusive": 0, "unscoreable": 0, "open": 0},
                    hit_rate=None, hit_rate_ci=None, resolved_scoreable=0, links=0, brand="Rhumb"),
                presentation.score_card_svg("NVDA", "NVIDIA", 80, "high", "a headline",
                                            brand="Rhumb")):
        assert "TRADEOSS" not in svg.upper().replace("<TSPAN", "").replace("</TSPAN>", "")
        assert "RHUMB" in svg.upper()


# ------------------------------------------------------------------ rate limiting

def test_publishing_and_reading_a_call_are_limited_separately():
    """`/api/calls` is a publish on POST and a public read of one call on GET. Sharing a bucket
    would let twenty page views an hour exhaust an allowance meant for writes."""
    from tradeos.app import _limit_bucket
    assert _limit_bucket("/api/calls", "POST") == "publish"
    assert _limit_bucket("/api/calls/17", "GET") == "public"
    assert _limit_bucket("/api/receipts/someone", "GET") == "public"
    assert _limit_bucket("/api/board", "GET") == "public"
    assert _limit_bucket("/r/someone", "GET") == "public"


# ------------------------------------------------------------------ what may become a link
#
# Found by /security-review on this change. `audience_url` was stored with no scheme validation and
# rendered as the href of a link on a PUBLIC record page. React escapes an attribute value but does
# not restrict the SCHEME, so `javascript:` survived to something any visitor could click, in the
# app's own origin, where a same-origin fetch carries the session cookie. Every other user-supplied
# URL in this feature was already checked; this was the one that reached an href without it.

def test_a_non_https_audience_link_is_refused(client, monkeypatch):
    """Refused at the write path, not coerced. A value quietly rewritten is a caller believing they
    said something they did not say, and this one ends up on a public page."""
    import tradeos.app as app_mod

    monkeypatch.setattr(app_mod.authn, "session_user", lambda conn, token: {"id": -1, "tier": "pro"})
    monkeypatch.setattr(app_mod, "_caller_for_user", lambda conn, uid: None)
    for bad in ("javascript:alert(1)", "JaVaScRiPt:alert(1)", "data:text/html,<script>x</script>",
                "http://example.com", "//example.com"):
        r = client.post("/api/callers", json={"handle": "probe-scheme", "display_name": "P",
                                              "audience_url": bad, "jurisdiction_attested": True})
        assert r.status_code == 400, f"{bad!r} was accepted"
        assert "https" in r.json()["error"]


def test_the_record_page_refuses_to_render_a_link_it_did_not_vet():
    """The second lock, in the component. The server refuses these on the way in; this is what
    stops a row written by a path that does not exist yet from becoming a link."""
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "frontend" / "src" / "record.jsx").read_text()
    assert "function httpsOnly(url)" in src
    assert "href={httpsOnly(caller.audience_url)}" in src
    assert "href={httpsOnly(caller.verification_evidence_url)}" in src
    assert "href={caller.audience_url}" not in src


def test_the_share_page_escapes_every_interpolation():
    """The card path was the one value on /r/{handle} that was not escaped. It is safe today only
    because of a regex three hundred lines away in a different function."""
    import inspect

    import tradeos.app as app_mod
    src = inspect.getsource(app_mod.receipt_share_page)
    assert 'card = e(f"/api/card/receipt/' in src
    # Nothing else may be interpolated raw into an attribute on that page.
    for raw in ('content="{title}"', 'content="{line}"', 'href="/record?handle={caller'):
        assert raw not in src
