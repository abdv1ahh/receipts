"""Offline tests for the Ledger's scoring rules.

These encode the three decisions that make a published hit rate worth believing: excess return
rather than raw, a noise floor below which nothing is credited, and `unscoreable` as a counted
verdict rather than a silent exclusion. Get any of them wrong and the number flatters itself.
"""
import pytest

from tradeos import ledger

# ------------------------------------------------------------------ verdicts

def test_a_correct_call_that_moved_enough_is_a_hit():
    assert ledger.verdict_for("up", 0.08)[0] == "hit"
    assert ledger.verdict_for("down", -0.08)[0] == "hit"


def test_a_wrong_call_that_moved_enough_is_a_miss():
    assert ledger.verdict_for("up", -0.08)[0] == "miss"
    assert ledger.verdict_for("down", 0.08)[0] == "miss"


@pytest.mark.parametrize("excess", [0.0, 0.005, -0.005, 0.019, -0.019])
def test_a_move_inside_the_noise_floor_is_inconclusive_not_a_hit(excess):
    """A claim that said 'up' and produced +0.3% has not been demonstrated right. Counting that as
    a hit is the easiest way to inflate a track record, so it is explicitly refused."""
    verdict, note = ledger.verdict_for("up", excess)
    assert verdict == "inconclusive"
    assert "noise floor" in note


def test_the_noise_floor_boundary_is_exact():
    assert ledger.verdict_for("up", ledger.NOISE_FLOOR)[0] == "hit"
    assert ledger.verdict_for("up", ledger.NOISE_FLOOR - 0.0001)[0] == "inconclusive"


def test_no_price_series_is_unscoreable_and_says_why():
    """Currencies and regions have no series here. Dropping them silently would let the hit rate be
    computed over a self-selected sample."""
    verdict, note = ledger.verdict_for("up", None)
    assert verdict == "unscoreable" and "no price series" in note


def test_every_verdict_is_one_the_schema_allows():
    allowed = {"hit", "miss", "inconclusive", "unscoreable"}
    for direction in ("up", "down"):
        for excess in (None, -0.5, -0.01, 0.0, 0.01, 0.5):
            assert ledger.verdict_for(direction, excess)[0] in allowed


# ------------------------------------------------------------------ confidence buckets

@pytest.mark.parametrize("confidence,expected", [
    (0.0, "low"), (0.2, "low"), (0.39, "low"),
    (0.4, "medium"), (0.55, "medium"), (0.69, "medium"),
    (0.7, "high"), (0.9, "high"), (1.0, "high"),
])
def test_confidence_buckets_partition_the_range(confidence, expected):
    assert ledger.confidence_bucket(confidence) == expected


# ------------------------------------------------------------------ sample sufficiency

def test_a_thin_slice_is_marked_insufficient_rather_than_shown_as_a_rate():
    """2 of 3 must never render as '67% accurate'."""
    thin = ledger._rate("monetary_policy", hits=2, misses=1, min_sample=20)
    assert thin["hit_rate"] == 0.667 and thin["sufficient"] is False


def test_a_real_sample_is_marked_sufficient():
    real = ledger._rate("earnings", hits=14, misses=10, min_sample=20)
    assert real["n"] == 24 and real["sufficient"] is True


def test_an_empty_slice_reports_no_rate_rather_than_zero():
    """0/0 is 'unknown', not '0% accurate'."""
    empty = ledger._rate("conflict", hits=0, misses=0, min_sample=20)
    assert empty["hit_rate"] is None and empty["n"] == 0


def test_an_uncategorised_slice_is_labelled_not_dropped():
    assert ledger._rate(None, 3, 2, 20)["key"] == "uncategorised"
