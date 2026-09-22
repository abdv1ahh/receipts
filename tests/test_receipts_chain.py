"""The hash chain, which is the product's central claim, tested against every way of breaking it.

If these pass and the chain is still forgeable, the whole thing is theatre. So the cases are not
"does it hash" but "can a specific edit go unnoticed": change a field, remove a link, swap two,
re-point a prev_hash. Each has to be caught AND has to name the right seq, because a verifier that
says "something is wrong somewhere" is not evidence a reader can use.
"""
from __future__ import annotations

import copy
import json
import pathlib
from datetime import UTC, datetime, timedelta, timezone

import pytest

from tradeos.receipts import chain

BASE = datetime(2026, 5, 1, 14, 30, 0, 123456, tzinfo=UTC)


def make_call(seq: int, **over) -> dict:
    call = {"caller_id": 7, "seq": seq, "symbol": "AAPL", "direction": "up", "horizon_days": 30,
            "confidence": "medium", "thesis": f"thesis number {seq}, long enough to be a real one",
            "benchmark_symbol": "SPY", "published_at": BASE + timedelta(days=seq),
            "knowable_time": BASE + timedelta(days=seq)}
    call.update(over)
    return call


def build(n: int) -> list[dict]:
    """A sealed chain of n calls, exactly as `calls.publish` would have written them."""
    out, prev = [], chain.GENESIS_HASH
    for seq in range(1, n + 1):
        call = make_call(seq)
        _payload, digest = chain.seal(call, prev)
        call["prev_hash"], call["content_hash"] = prev, digest
        out.append(call)
        prev = digest
    return out


# ------------------------------------------------------------------ the payload is a wire format

def test_the_payload_is_stable_across_timezones_and_representations():
    """A call sealed by a server in Dubai and one in UTC must produce identical bytes, or the same
    record would fail its own verification after a deploy to a different host."""
    utc = make_call(1)
    gulf = make_call(1, published_at=utc["published_at"].astimezone(timezone(timedelta(hours=4))))
    gulf["knowable_time"] = gulf["published_at"]
    assert chain.canonical_payload(utc) == chain.canonical_payload(gulf)


def test_a_naive_timestamp_is_refused_rather_than_guessed():
    call = make_call(1, published_at=datetime(2026, 5, 1, 14, 30))
    with pytest.raises(ValueError):
        chain.canonical_payload(call)


def test_a_missing_sealed_field_is_refused():
    call = make_call(1)
    del call["thesis"]
    with pytest.raises(KeyError):
        chain.canonical_payload(call)


def test_free_text_cannot_be_mistaken_for_structure():
    """The reason fields are length prefixed rather than delimited.

    A caller writes their own thesis. With a plain separator they could type the separator into it
    and make two genuinely different calls serialise to the same bytes, which is a collision they
    control and therefore a forged link. Two calls that differ only in where the boundary falls
    must never produce one payload.
    """
    a = make_call(1, symbol="AAPL", thesis="x" * 40 + "\nsymbol:4:MSFT")
    b = make_call(1, symbol="AAPL\nsymbol:4:MSFT", thesis="x" * 40)
    assert chain.canonical_payload(a) != chain.canonical_payload(b)


def test_the_sealed_field_order_is_frozen():
    """Reordering or adding a sealed field would invalidate every chain ever published. This test
    exists to make that an explicit decision rather than an accident in a refactor."""
    assert chain.SEALED_FIELDS == (
        "caller_id", "seq", "symbol", "direction", "horizon_days", "confidence", "thesis",
        "benchmark_symbol", "published_at", "knowable_time")


# ------------------------------------------------------------------ verification

def test_a_genesis_link_verifies():
    calls = build(1)
    assert calls[0]["prev_hash"] == chain.GENESIS_HASH
    result = chain.verify_chain(calls)
    assert result["intact"] is True
    assert result["links"] == 1
    assert result["broken_at_seq"] is None


def test_an_empty_record_is_intact_and_says_so():
    """A caller who has published nothing has not broken anything. Reporting a new caller's empty
    record as a broken chain would be the first thing they ever saw."""
    result = chain.verify_chain([])
    assert result["intact"] is True and result["links"] == 0
    assert result["head"] == chain.GENESIS_HASH


def test_a_long_chain_verifies_and_is_order_independent_on_input():
    calls = build(40)
    assert chain.verify_chain(calls)["intact"] is True
    shuffled = list(reversed(calls))
    result = chain.verify_chain(shuffled)
    assert result["intact"] is True and result["links"] == 40


def test_editing_a_thesis_breaks_the_chain_at_that_call():
    calls = build(10)
    calls[4]["thesis"] = "a completely different thesis, quietly substituted after the fact"
    result = chain.verify_chain(calls)
    assert result["intact"] is False
    assert result["broken_at_seq"] == 5
    assert "contents" in result["reason"]


def test_backdating_a_call_breaks_the_chain():
    """The edit a track record would most want to make: move a call earlier so it looks prescient."""
    calls = build(6)
    calls[3]["published_at"] = BASE - timedelta(days=90)
    assert chain.verify_chain(calls)["broken_at_seq"] == 4


def test_flipping_a_direction_breaks_the_chain():
    calls = build(6)
    calls[2]["direction"] = "down"
    assert chain.verify_chain(calls)["broken_at_seq"] == 3


def test_removing_a_call_is_caught_as_a_gap():
    """Deleting a loser is the whole thing this is built to stop."""
    calls = build(8)
    without = [c for c in calls if c["seq"] != 5]
    result = chain.verify_chain(without)
    assert result["intact"] is False
    assert result["broken_at_seq"] == 6            # the first seq that is not where it should be
    assert "missing" in result["reason"]


def test_removing_the_last_call_is_caught_by_the_head_moving():
    """A truncation leaves every remaining link self consistent, so it cannot be caught by hashes
    alone. It is caught because the published head no longer matches."""
    calls = build(8)
    head_before = chain.verify_chain(calls)["head"]
    truncated = [c for c in calls if c["seq"] != 8]
    result = chain.verify_chain(truncated)
    assert result["intact"] is True                # internally consistent, and that is the point
    assert result["head"] != head_before           # but it is a different record than was published
    assert result["links"] == 7


def test_swapping_two_calls_breaks_the_chain():
    calls = build(6)
    calls[2]["seq"], calls[3]["seq"] = calls[3]["seq"], calls[2]["seq"]
    result = chain.verify_chain(calls)
    assert result["intact"] is False
    assert result["broken_at_seq"] == 3


def test_a_duplicated_sequence_number_is_caught():
    calls = build(5)
    calls[3]["seq"] = 3
    assert chain.verify_chain(calls)["intact"] is False


def test_repointing_a_prev_hash_is_caught():
    """An attacker who understands the format would fix the prev_hash to match their edit. Then the
    content_hash no longer matches, because the content hash covers the prev hash."""
    calls = build(6)
    calls[3]["prev_hash"] = "f" * 64
    result = chain.verify_chain(calls)
    assert result["broken_at_seq"] == 4
    assert "chain from" in result["reason"]


def test_a_fully_recomputed_forgery_is_the_hole_we_do_not_close():
    """Documented, not fixed, and stated on the methodology page in these terms.

    Anyone holding every field can rewrite a call and recompute the entire chain after it. That is
    the operator, which is us. The chain is tamper evident against the CALLER, and this test exists
    so nobody later mistakes it for more than that.
    """
    calls = build(6)
    forged = copy.deepcopy(calls)
    forged[2]["thesis"] = "a thesis rewritten by the operator after the outcome was known"
    prev = chain.GENESIS_HASH
    for call in forged:
        _p, digest = chain.seal(call, prev)
        call["prev_hash"], call["content_hash"] = prev, digest
        prev = digest
    assert chain.verify_chain(forged)["intact"] is True     # and this is why an anchor is needed
    assert chain.verify_chain(forged)["head"] != chain.verify_chain(calls)["head"]


def test_the_first_break_is_the_one_reported():
    """Once a link breaks, every later link is computed over a wrong prev_hash and is broken too.
    Reporting the earliest is what points at the actual edit rather than at its consequences."""
    calls = build(10)
    calls[2]["symbol"] = "MSFT"
    calls[7]["symbol"] = "TSLA"
    assert chain.verify_chain(calls)["broken_at_seq"] == 3


# ------------------------------------------------------------------ handing the payload to a browser

def test_the_rendered_fields_reassemble_into_the_canonical_payload():
    """A browser cannot be sent a datetime, and it must not be asked to reinvent how one is
    rendered: microseconds and the trailing Z are part of the sealed bytes, and a JavaScript Date
    round trip drops both. So the server renders each field and the browser only frames and hashes.

    This pins the two against each other. If `rendered_fields` ever stops reproducing
    `canonical_payload` exactly, every visitor's own check would report an intact record broken.
    """
    call = make_call(1)
    rendered = chain.rendered_fields(call)
    assert list(rendered) == list(chain.SEALED_FIELDS)
    assert all(isinstance(v, str) for v in rendered.values())
    framed = "\n".join(f"{k}:{len(v.encode('utf-8'))}:{v}" for k, v in rendered.items())
    assert framed == chain.canonical_payload(call)


def test_the_rendered_timestamp_keeps_its_microseconds_and_its_z():
    """The two halves a Date round trip loses, asserted on their own so the reason is visible when
    this fails rather than buried in a payload comparison."""
    rendered = chain.rendered_fields(make_call(1))
    assert rendered["published_at"] == "2026-05-02T14:30:00.123456Z"


# ------------------------------------------------------------------ the cross-language fixture

FIXTURE = pathlib.Path(__file__).resolve().parent / "fixtures" / "receipt_chain.json"


def test_python_still_reproduces_every_hash_in_the_shared_fixture():
    """The Python half of the guard against `chain.py` and `receipts/verify.js` drifting apart.

    `make test` runs inside the API image, which carries no node, and the host that has node has no
    Python dependencies — so no single place can run both. Both sides check this one committed
    fixture instead: five links sealed by `chain.seal`, including an empty thesis, a four-byte
    emoji, and a thesis that spells out a field header to try to smuggle structure past the
    framing. `tests/verify_js_check.mjs` (via `make test-js`) asserts JavaScript reproduces it.
    Pinning both to one file pins them to each other.

    If this fails, the wire format has changed and every chain ever published is now unverifiable.
    That is not a test to update — see the module docstring in `chain.py`.
    """
    body = json.loads(FIXTURE.read_text())
    assert body["fields"] == list(chain.SEALED_FIELDS)
    assert body["genesis"] == chain.GENESIS_HASH

    prev = chain.GENESIS_HASH
    for link in body["links"]:
        payload = "\n".join(f"{name}:{len(value.encode('utf-8'))}:{value}"
                            for name, value in link["values"].items())
        assert link["prev_hash"] == prev
        assert chain.content_hash(payload, prev) == link["content_hash"], link["seq"]
        prev = link["content_hash"]


def test_the_fixture_exercises_the_cases_the_framing_exists_for():
    """A fixture of five ordinary calls would pass under a verifier that used character counts and
    under one that joined with a delimiter. These are the three rows that make it a real test."""
    values = [link["values"] for link in json.loads(FIXTURE.read_text())["links"]]
    theses = [v["thesis"] for v in values]
    assert any(t == "" for t in theses), "an empty thesis must be in the fixture"
    assert any(len(t.encode("utf-8")) != len(t) for t in theses), "a multi-byte thesis must be in"
    assert any(":" in t and "seq:" in t for t in theses), "a thesis imitating a field header"
