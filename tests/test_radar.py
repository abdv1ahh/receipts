"""Offline tests for the Phase 4 remainder: filter specs, threading, and the webhook SSRF defence.

The SSRF tests are the ones that matter. A webhook URL is supplied by a user and fetched by the
server, which is the definition of SSRF — and the danger is not the public internet, it is that the
server can reach things the user cannot: a cloud metadata endpoint holding credentials, a database
on a private subnet, another container by name.
"""
import inspect
from unittest.mock import patch

import pytest

from tradeos import radar

# ------------------------------------------------------------------ the filter spec

def test_a_spec_is_coerced_to_a_fixed_shape():
    """An allowlist, not a sanitiser: the stored spec can only ever hold these five keys, so
    `matches()` never has to defend itself against a shape it did not expect."""
    out = radar.normalise_spec({"categories": ["energy"], "junk": "dropped",
                                "geo": ["ae"], "horizons": ["days", "millennia"],
                                "min_confidence": "0.7"})
    assert set(out) == {"categories", "geo", "horizons", "sources", "min_confidence"}
    assert out["geo"] == ["AE"]                       # normalised
    assert out["horizons"] == ["days"]                # unknown horizon dropped
    assert out["min_confidence"] == 0.7               # coerced from a string


def test_a_hostile_or_absent_spec_becomes_an_empty_one_rather_than_raising():
    for bad in (None, [], "spec", {"geo": "AE"}, {"min_confidence": "nonsense"}):
        out = radar.normalise_spec(bad)
        assert out["geo"] == [] or out["geo"] == []
        assert 0.0 <= out["min_confidence"] <= 1.0


def test_confidence_is_clamped():
    assert radar.normalise_spec({"min_confidence": 5})["min_confidence"] == 1.0
    assert radar.normalise_spec({"min_confidence": -3})["min_confidence"] == 0.0


CLAIM = {"category": "energy", "horizon": "days", "confidence": 0.8, "source": "rss/cnbc-top",
         "geo": ["US"], "affected": [{"kind": "region", "value": "Middle East", "direction": "up"}]}


def test_an_empty_dimension_means_no_constraint():
    """A fresh filter shows everything. The opposite — empty means match nothing — would make a
    half-built filter look broken."""
    assert radar.matches(CLAIM, radar.normalise_spec({}))


def test_each_dimension_filters():
    assert not radar.matches(CLAIM, radar.normalise_spec({"categories": ["crypto"]}))
    assert not radar.matches(CLAIM, radar.normalise_spec({"horizons": ["months"]}))
    assert not radar.matches(CLAIM, radar.normalise_spec({"sources": ["rss/fed"]}))
    assert not radar.matches(CLAIM, radar.normalise_spec({"min_confidence": 0.9}))
    assert radar.matches(CLAIM, radar.normalise_spec({"categories": ["energy"], "min_confidence": 0.5}))


def test_the_geography_filter_uses_what_the_claim_affects_not_who_published_it():
    """The project's most repeated mistake, and a filter is a new place to make it. This claim was
    filed by a US outlet about the Middle East: a Gulf filter must catch it, and a US filter must
    not — the reverse of what `geo` alone would give."""
    assert radar.matches(CLAIM, radar.normalise_spec({"geo": ["AE"]}))
    assert not radar.matches(CLAIM, radar.normalise_spec({"geo": ["US"]}))


# ------------------------------------------------------------------ threading

def _c(cid, claim_id, when, conf, affected=None):
    return {"cluster_id": cid, "id": claim_id, "created_at": when, "confidence": conf,
            "relevance": 0.5, "affected": affected or []}


def test_one_story_becomes_one_card_with_its_history():
    """Twelve near-duplicates is the thing threading exists to prevent."""
    out = radar.thread([_c(1, 10, "2026-07-01", 0.6), _c(1, 20, "2026-07-03", 0.8)])
    assert len(out) == 1
    assert out[0]["id"] == 20 and out[0]["revisions"] == 1
    assert [h["id"] for h in out[0]["history"]] == [10]


def test_the_history_is_returned_not_hidden():
    """A reader can only watch the system change its mind if it still says what it used to."""
    out = radar.thread([_c(1, 10, "2026-07-01", 0.6), _c(1, 20, "2026-07-03", 0.8)])
    assert out[0]["history"][0]["confidence"] == 0.6


def test_a_claim_with_no_cluster_stands_alone():
    out = radar.thread([{"cluster_id": None, "id": 5, "created_at": "2026-07-01", "relevance": 0.9}])
    assert len(out) == 1 and out[0]["revisions"] == 0


def test_what_changed_names_a_confidence_move():
    out = radar.thread([_c(1, 10, "2026-07-01", 0.6), _c(1, 20, "2026-07-03", 0.75)])
    assert "60% to 75%" in out[0]["changed"]["summary"]


def test_what_changed_names_a_reversal():
    before = _c(1, 10, "2026-07-01", 0.6, [{"kind": "asset", "value": "NVDA", "direction": "up"}])
    after = _c(1, 20, "2026-07-03", 0.6, [{"kind": "asset", "value": "NVDA", "direction": "down"}])
    out = radar.thread([before, after])
    assert out[0]["changed"]["reversed"] == ["NVDA"]
    assert "reversed direction on NVDA" in out[0]["changed"]["summary"]


def test_what_changed_says_so_when_the_reading_held():
    out = radar.thread([_c(1, 10, "2026-07-01", 0.7), _c(1, 20, "2026-07-03", 0.7)])
    assert "held" in out[0]["changed"]["summary"]


def test_threads_stay_ordered_by_relevance():
    a = {**_c(1, 10, "2026-07-01", 0.6), "relevance": 0.2}
    b = {**_c(2, 20, "2026-07-02", 0.6), "relevance": 0.9}
    assert [t["id"] for t in radar.thread([a, b])] == [20, 10]


def test_a_superseded_claim_is_never_withdrawn_from_the_ledger():
    """The rule that keeps revision honest. If a revision removed the original from the record,
    changing its mind would be a mechanism for erasing misses."""
    from tradeos import claims

    src = inspect.getsource(claims.reinterpret_developing)
    for withdrawal in ("status='unscoreable'", "DELETE FROM claims", "resolved_at", "status='withdrawn'"):
        assert withdrawal not in src, f"re-interpretation touches {withdrawal!r}"


def test_a_story_is_re_read_only_when_it_actually_grew():
    """Re-running the model on unchanged input would spend quota to reword the same thing and call
    it a revision."""
    from tradeos import claims

    src = inspect.getsource(claims.reinterpret_developing)
    assert "c.source_count >= latest.n_sources + %s" in src


# ------------------------------------------------------------------ SSRF

@pytest.mark.parametrize("url,why", [
    ("http://example.com/hook", "https"),
    ("ftp://example.com/hook", "https"),
    ("https://", "host"),
    ("not a url at all", "https"),
])
def test_only_https_with_a_host_is_accepted(url, why):
    ok, reason = radar.webhook_target_ok(url)
    assert not ok and why in reason


@pytest.mark.parametrize("ip", [
    "127.0.0.1",          # loopback
    "169.254.169.254",    # cloud metadata — credentials
    "10.0.0.5",           # private
    "192.168.1.1",        # private
    "172.16.0.1",         # private
    "0.0.0.0",            # unspecified  # noqa: S104 — an address under test, not a bind
    "224.0.0.1",          # multicast
])
def test_a_host_resolving_to_infrastructure_is_refused(ip):
    """The danger is not the public internet — it is that the server can reach things the user
    cannot. Checked on the RESOLVED address, because a hostname check loses to a DNS record that
    points at 127.0.0.1."""
    with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", (ip, 443))]):
        ok, reason = radar.webhook_target_ok("https://looks-fine.example.com/hook")
    assert not ok and "private or reserved" in reason


def test_every_resolved_address_must_pass_not_just_the_first():
    """A name resolving to one public and one private address would otherwise be accepted, and the
    client could then connect to whichever it picked."""
    with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 443)),
                                                   (2, 1, 6, "", ("127.0.0.1", 443))]):
        ok, _ = radar.webhook_target_ok("https://example.com/hook")
    assert not ok


def test_a_public_https_endpoint_is_accepted():
    with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 443))]):
        ok, reason = radar.webhook_target_ok("https://example.com/hook")
    assert ok and reason == ""


def test_infrastructure_ports_are_refused():
    for port in (22, 5432, 6379, 27017):
        ok, reason = radar.webhook_target_ok(f"https://example.com:{port}/hook")
        assert not ok and "webhook endpoint" in reason


def test_the_target_is_rechecked_at_send_time_and_redirects_are_refused():
    """DNS can change between saving and sending — that is exactly a rebinding attack. And a 302 to
    the metadata service would walk straight past a check that just passed."""
    src = inspect.getsource(radar._send_webhook)
    assert "webhook_target_ok(url)" in src
    assert "follow_redirects=False" in src


# ------------------------------------------------------------------ throttling

def test_the_throttle_floor_cannot_be_undercut_by_a_client():
    src = inspect.getsource(radar.save)
    assert "max(MIN_THROTTLE_MINS," in src


def test_delivery_advances_a_claim_id_high_water_mark_not_a_timestamp():
    """Ids are monotonic; a timestamp comparison would resend anything written during the same
    second as the previous run."""
    src = inspect.getsource(radar.deliver_due)
    assert "last_claim_id=%s" in src
    assert "_claims_since(cur, since)" in src


def test_nothing_is_sent_when_nothing_matched():
    """An alert that says "no news" is the noise a throttle exists to prevent."""
    src = inspect.getsource(radar.deliver_due)
    assert "if hits and email:" in src


def test_a_subscription_must_name_a_channel():
    src = inspect.getsource(radar.save)
    assert 'return {"error": "choose email or webhook to subscribe"}' in src
