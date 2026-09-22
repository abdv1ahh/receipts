"""Offline tests for the scoring rules and the statistics a record may quote.

These were `ledger.py`'s, and they moved with the functions when the Ledger surface was deleted and
its pure parts were lifted into `stats.py` and `prices.py`. They encode the decisions that make a
published hit rate worth believing: excess return rather than raw, a noise floor below which
nothing is credited, `unscoreable` as a counted verdict rather than a silent exclusion, and an
interval beside every point estimate. Get any of them wrong and the number flatters itself.

The four-way split in UNSCOREABLE_REASONS is the one worth reading twice. Two of the reasons are
the SUBJECT's fault and two are OURS, and before that split existed a single missing SPY session
permanently sealed a healthy call as unscoreable while blaming the subject's feed. A verdict
cannot be taken back, so a reason that names the wrong side is not cosmetic.
"""
import pytest

from tradeos import prices, stats

# ------------------------------------------------------------------ verdicts

def test_a_correct_call_that_moved_enough_is_a_hit():
    assert prices.verdict_for("up", 0.08)[0] == "hit"
    assert prices.verdict_for("down", -0.08)[0] == "hit"


def test_a_wrong_call_that_moved_enough_is_a_miss():
    assert prices.verdict_for("up", -0.08)[0] == "miss"
    assert prices.verdict_for("down", 0.08)[0] == "miss"


@pytest.mark.parametrize("excess", [0.0, 0.005, -0.005, 0.019, -0.019])
def test_a_move_inside_the_noise_floor_is_inconclusive_not_a_hit(excess):
    """A claim that said 'up' and produced +0.3% has not been demonstrated right. Counting that as
    a hit is the easiest way to inflate a track record, so it is explicitly refused."""
    verdict, note = prices.verdict_for("up", excess)
    assert verdict == "inconclusive"
    assert "noise floor" in note


def test_the_noise_floor_boundary_is_exact():
    assert prices.verdict_for("up", stats.NOISE_FLOOR)[0] == "hit"
    assert prices.verdict_for("up", stats.NOISE_FLOOR - 0.0001)[0] == "inconclusive"


def test_no_price_series_is_unscoreable_and_says_why():
    """Currencies and regions have no series here. Dropping them silently would let the hit rate be
    computed over a self-selected sample."""
    verdict, note = prices.verdict_for("up", None)
    assert verdict == "unscoreable" and "no price series" in note


def test_every_verdict_is_one_the_schema_allows():
    allowed = {"hit", "miss", "inconclusive", "unscoreable"}
    for direction in ("up", "down"):
        for excess in (None, -0.5, -0.01, 0.0, 0.01, 0.5):
            assert prices.verdict_for(direction, excess)[0] in allowed


# ------------------------------------------------------------------ the note must be TRUE
#
# All 273 unscoreable rows carried one sentence — "no price series for this subject" — and it was
# wrong for most of them. `measure_claim` bound `excess_return`'s reason to `_why` and discarded
# it, so a subject that is a REGION and a subject whose price feed merely stopped two days early
# produced byte-identical diagnostics. BA and SPY have 1,293 price rows each and were both filed
# under "no price series".

def test_an_unscoreable_note_reports_the_reason_it_was_given():
    for key, template in prices.UNSCOREABLE_REASONS.items():
        note = template.format(subject="EURUSD", kind="currency")
        verdict, got = prices.verdict_for("up", None, note)
        assert verdict == "unscoreable"
        assert got == note, f"{key} was replaced by a generic note"


def test_a_stale_feed_does_not_masquerade_as_a_missing_one():
    """The two failures that looked identical. One is a permanent property of the subject; the
    other is an operational fault someone can fix this afternoon."""
    missing = prices.verdict_for("up", None, prices.UNSCOREABLE_REASONS["no_symbol"])[1]
    stale = prices.verdict_for("up", None, prices.UNSCOREABLE_REASONS["no_entry_price"])[1]
    assert missing != stale
    assert "feed ends" in stale and "feed ends" not in missing


def test_every_reason_excess_return_can_return_has_a_sentence():
    """`excess_return`'s second element is the vocabulary; a reason with no entry here would fall
    back to the generic note and re-create the bug for that one case."""
    from datetime import date

    from tradeos.backtest.engine import Series, excess_return
    spy = Series.from_rows([(date(2025, 1, 2), 100.0), (date(2025, 2, 3), 110.0)])
    sym = Series.from_rows([(date(2025, 1, 2), 10.0)])
    # series ends before the claim -> no entry price
    assert excess_return(sym, spy, date(2025, 6, 1), 30)[1] == "no_entry_price"
    # entry exists but the horizon has not closed in the data -> horizon open
    assert excess_return(sym, spy, date(2024, 12, 1), 30)[1] == "horizon_open_or_delisted"
    # the benchmark's own gaps, which used to arrive wearing the subject's reasons
    full = Series.from_rows([(date(2025, 1, 2), 10.0), (date(2025, 1, 3), 10.0),
                             (date(2025, 2, 3), 11.0)])
    # SPY holds the claim day but not the entry session the subject actually enters on
    missing_entry = Series.from_rows([(date(2025, 1, 2), 100.0)])
    assert excess_return(full, missing_entry, date(2025, 1, 2), 30)[1] == "no_benchmark_entry_price"
    # SPY holds the entry session but stops before the horizon closes
    missing_exit = Series.from_rows([(date(2025, 1, 3), 100.0)])
    assert excess_return(full, missing_exit, date(2025, 1, 2), 30)[1] == "no_benchmark_exit_price"
    for reason in ("no_entry_price", "horizon_open_or_delisted",
                   "no_benchmark_entry_price", "no_benchmark_exit_price"):
        assert reason in prices.UNSCOREABLE_REASONS


def test_a_benchmark_gap_does_not_wear_the_subject_s_sentence():
    """The Receipts plane seals on some of these reasons and not others, so the sentences have to
    be distinguishable by a reader as well as by a `==`."""
    subject = prices.UNSCOREABLE_REASONS["no_entry_price"]
    bench_in = prices.UNSCOREABLE_REASONS["no_benchmark_entry_price"]
    bench_out = prices.UNSCOREABLE_REASONS["no_benchmark_exit_price"]
    assert subject != bench_in != bench_out
    for note in (bench_in, bench_out):
        assert "benchmark" in note
    assert "benchmark" not in subject


def test_a_non_asset_subject_says_what_kind_it_was():
    """88.7% of the impact engine's subjects are sectors, regions, commodities and currencies. The
    note has to name the kind, or the reader cannot tell a vocabulary problem from a data gap."""
    note = prices.UNSCOREABLE_REASONS["not_priceable_kind"].format(subject="TECHNOLOGY",
                                                                   kind="sector")
    assert "TECHNOLOGY" in note and "sector" in note
    assert prices.verdict_for("up", None, note)[1] == note


def test_a_scoreable_subject_ignores_the_reason_entirely():
    """`excess_return` returns 'ok' alongside a real number; that must never reach a note."""
    verdict, note = prices.verdict_for("up", 0.08, "ok")
    assert verdict == "hit" and note is None


# ------------------------------------------------------------------ confidence buckets

@pytest.mark.parametrize("confidence,expected", [
    (0.0, "low"), (0.2, "low"), (0.39, "low"),
    (0.4, "medium"), (0.55, "medium"), (0.69, "medium"),
    (0.7, "high"), (0.9, "high"), (1.0, "high"),
])
def test_confidence_buckets_partition_the_range(confidence, expected):
    assert stats.confidence_bucket(confidence) == expected


# ------------------------------------------------------------------ sample sufficiency
def _db_reachable() -> bool:
    try:
        from tradeos import db
        with db.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
        return True
    except Exception:
        return False


needs_db = pytest.mark.skipif(not _db_reachable(), reason="ledger summary reads the database")
def test_a_mean_whose_interval_spans_zero_is_not_significant():
    # Symmetric noise around a small negative mean — exactly the ledger's real situation.
    vals = [0.15, -0.13, 0.16, -0.14, 0.10, -0.12, 0.18, -0.20]
    out = stats.mean_ci(vals)
    assert out["lo"] < 0 < out["hi"]
    assert out["significant"] is False


def test_a_real_effect_is_reported_as_significant():
    vals = [0.05, 0.06, 0.055, 0.048, 0.052, 0.058, 0.051, 0.049] * 4
    out = stats.mean_ci(vals)
    assert out["lo"] > 0
    assert out["significant"] is True


def test_mean_ci_degrades_rather_than_dividing_by_zero():
    assert stats.mean_ci([])["n"] == 0
    assert stats.mean_ci([])["significant"] is False
    one = stats.mean_ci([0.1])
    assert one["n"] == 1 and one["significant"] is False   # one call proves nothing


def test_proportion_z_measures_distance_from_a_coin_flip():
    assert stats.proportion_z(115, 282) == pytest.approx(-3.10, abs=0.05)
    assert stats.proportion_z(50, 100) == pytest.approx(0.0, abs=0.01)
    assert stats.proportion_z(0, 0) is None


def test_sample_needed_says_what_it_would_take_to_know():
    """The number that turns "we cannot tell yet" from an excuse into a plan. At the 18% dispersion
    actually measured, a 1% per-call edge needs roughly 1,300-1,500 resolved calls."""
    n = stats.sample_needed(0.183, 0.01)
    assert 1200 < n < 1600
    # A bigger edge is cheaper to prove.
    assert stats.sample_needed(0.183, 0.03) < n
    assert stats.sample_needed(0, 0.01) is None
