"""Slice 3 offline tests for the convergence signal: a frozen characterization dataset
locking exact scores, the independence-collapse and publish-gate logic, freshness decay,
the liquidity-floor bucket rule, and the version-lock guard. No network, no database.

The characterization test is the "signals never silently change meaning" tripwire: change
a base weight, the magnitude formula, or the collapse rule, and the exact score moves and
this test fails — which (with the code_hash lock) forces a logged version bump.
"""
from datetime import datetime, timedelta, timezone

import pytest

from tradeos.signals import convergence as cv
from tradeos.signals.definitions import DefinitionMismatch, check_definition

AS_OF = datetime(2026, 7, 15, tzinfo=timezone.utc)


def _ev(subtype, voice, magnitude=None, age_days=0.0):
    return cv.Event(subtype=subtype, voice_key=voice,
                    knowable_time=AS_OF - timedelta(days=age_days), magnitude=magnitude)


# --------------------------------------------------- frozen characterization dataset

def test_characterization_exact_score():
    """Three voices across two classes, all knowable exactly at as_of (decay = 1.0):
      voice insider:111 -> two purchases [1.0, 1.0] => 1.0 + 0.25*1.0 = 1.25
      voice insider:222 -> one purchase  [1.0]      => 1.0
      voice filer:900   -> one 13D new   [1.2]      => 1.2
      a sale on voice 111 is context (weight 0), not scored.
      total = 1.25 + 1.0 + 1.2 = 3.45
    """
    events = [
        _ev("insider_purchase", "insider:111", magnitude=999999),  # log10(1e6)/6 = 1.0
        _ev("insider_purchase", "insider:111", magnitude=None),    # unknown magnitude -> 1.0
        _ev("insider_sale", "insider:111", magnitude=None),        # context, scores 0
        _ev("insider_purchase", "insider:222", magnitude=None),
        _ev("stake_13d_new", "filer:900", magnitude=None),         # base 1.2, scale 1.0
    ]
    r = cv.score_cluster(events, AS_OF)
    assert r.score == 3.45
    assert r.voices == 3
    assert r.source_classes == ["activist", "insider"]
    assert r.passes_gate is True
    assert len(r.contributions) == 4   # the sale is in context, not contributions
    assert len(r.context) == 1
    assert cv.bucket_for(r.score, floor_ok=True, p=cv.DEFAULT_PARAMS) == "medium"


def test_magnitude_scaling_rules():
    p = cv.DEFAULT_PARAMS
    assert cv._magnitude_scale("insider_purchase", None, p) == 1.0            # unknown neutral
    assert cv._magnitude_scale("insider_purchase", 999999, p) == 1.0          # log10(1e6)/6
    assert cv._magnitude_scale("insider_purchase", 10**12, p) == 1.5          # capped
    assert cv._magnitude_scale("stake_13g", 12, p) == 1.2                     # percent 12 / 10
    assert cv._magnitude_scale("stake_13d_new", 100, p) == 1.5               # capped at 1.5


def test_freshness_decay_one_half_life():
    # a single insider purchase one half-life old (14 days): decayed weight = base * 1.0 * 0.5
    r = cv.score_cluster([_ev("insider_purchase", "insider:1", age_days=14)], AS_OF)
    assert r.score == pytest.approx(0.5, abs=1e-9)


# ------------------------------------------------------------------- publish gate

def test_gate_requires_two_classes():
    # three distinct insider voices but only one source class -> fails the gate
    events = [_ev("insider_purchase", f"insider:{i}") for i in (1, 2, 3)]
    r = cv.score_cluster(events, AS_OF)
    assert r.voices == 3 and r.source_classes == ["insider"]
    assert r.passes_gate is False


def test_gate_requires_three_voices():
    # two classes but only two voices -> fails the gate
    events = [_ev("insider_purchase", "insider:1"), _ev("stake_13g", "filer:9")]
    r = cv.score_cluster(events, AS_OF)
    assert r.voices == 2 and r.passes_gate is False


def test_institution_13d_and_13f_collapse_to_one_voice():
    # same filer entity filing a stake and (hypothetically scored) holding is ONE voice
    events = [
        _ev("stake_13d_new", "filer:900"),
        _ev("holding_13f", "filer:900", magnitude=1_000_000),  # would score if not same voice
        _ev("insider_purchase", "insider:111"),
    ]
    r = cv.score_cluster(events, AS_OF)
    assert r.voices == 2  # filer:900 counts once, insider:111 once


# ------------------------------------------------------------------ liquidity floor

def test_below_floor_forced_low():
    assert cv.bucket_for(9.0, floor_ok=False, p=cv.DEFAULT_PARAMS) == "low"
    assert cv.bucket_for(2.9, floor_ok=True, p=cv.DEFAULT_PARAMS) == "low"
    assert cv.bucket_for(3.0, floor_ok=True, p=cv.DEFAULT_PARAMS) == "medium"
    assert cv.bucket_for(6.0, floor_ok=True, p=cv.DEFAULT_PARAMS) == "medium"
    assert cv.bucket_for(6.01, floor_ok=True, p=cv.DEFAULT_PARAMS) == "high"


# ------------------------------------------------------------- version lock guard

def test_scorer_excludes_future_knowable_events():
    """Look-ahead guard (v2): an event not yet knowable at as_of is never counted, even if
    mis-fed to the scorer directly (defense-in-depth atop the SQL gather filter)."""
    valid = cv.Event("insider_purchase", "insider:1", AS_OF - timedelta(days=1), None)
    future = cv.Event("insider_purchase", "insider:2", AS_OF + timedelta(days=5), None)
    r = cv.score_cluster([valid, future], AS_OF)
    assert r.voices == 1
    assert [c["voice"] for c in r.contributions] == ["insider:1"]


def test_code_hash_is_stable_hex():
    h = cv.module_code_hash()
    assert len(h) == 64 and all(c in "0123456789abcdef" for c in h)
    assert h == cv.module_code_hash()  # deterministic


def test_compute_refuses_when_module_hash_changed():
    current = cv.module_code_hash()
    # a registered definition whose stored hash differs -> guard must refuse
    stale = {"version": 1, "code_hash": "deadbeef" * 8}
    with pytest.raises(DefinitionMismatch):
        check_definition(stale, "convergence", current)
    # no definition registered at all -> also refuse
    with pytest.raises(DefinitionMismatch):
        check_definition(None, "convergence", current)
    # matching hash -> passes
    assert check_definition({"version": 1, "code_hash": current}, "convergence", current)["version"] == 1
