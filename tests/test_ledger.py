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


# ------------------------------------------------------------------ the note must be TRUE
#
# All 273 unscoreable rows carried one sentence — "no price series for this subject" — and it was
# wrong for most of them. `measure_claim` bound `excess_return`'s reason to `_why` and discarded
# it, so a subject that is a REGION and a subject whose price feed merely stopped two days early
# produced byte-identical diagnostics. BA and SPY have 1,293 price rows each and were both filed
# under "no price series".

def test_an_unscoreable_note_reports_the_reason_it_was_given():
    for key, template in ledger.UNSCOREABLE_REASONS.items():
        note = template.format(subject="EURUSD", kind="currency")
        verdict, got = ledger.verdict_for("up", None, note)
        assert verdict == "unscoreable"
        assert got == note, f"{key} was replaced by a generic note"


def test_a_stale_feed_does_not_masquerade_as_a_missing_one():
    """The two failures that looked identical. One is a permanent property of the subject; the
    other is an operational fault someone can fix this afternoon."""
    missing = ledger.verdict_for("up", None, ledger.UNSCOREABLE_REASONS["no_symbol"])[1]
    stale = ledger.verdict_for("up", None, ledger.UNSCOREABLE_REASONS["no_entry_price"])[1]
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
    for reason in ("no_entry_price", "horizon_open_or_delisted"):
        assert reason in ledger.UNSCOREABLE_REASONS


def test_a_non_asset_subject_says_what_kind_it_was():
    """88.7% of the impact engine's subjects are sectors, regions, commodities and currencies. The
    note has to name the kind, or the reader cannot tell a vocabulary problem from a data gap."""
    note = ledger.UNSCOREABLE_REASONS["not_priceable_kind"].format(subject="TECHNOLOGY",
                                                                   kind="sector")
    assert "TECHNOLOGY" in note and "sector" in note
    assert ledger.verdict_for("up", None, note)[1] == note


def test_a_scoreable_subject_ignores_the_reason_entirely():
    """`excess_return` returns 'ok' alongside a real number; that must never reach a note."""
    verdict, note = ledger.verdict_for("up", 0.08, "ok")
    assert verdict == "hit" and note is None


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


# ------------------------------------------------------------------ the record must not mislead
#
# These need the local database, and skip like the adversarial authz tests do when it is absent.

def _db_reachable() -> bool:
    try:
        from tradeos import db
        with db.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
        return True
    except Exception:
        return False


needs_db = pytest.mark.skipif(not _db_reachable(), reason="ledger summary reads the database")


@needs_db
def test_the_summary_reports_magnitude_not_only_a_hit_rate():
    """A hit rate on its own is misleading in BOTH directions — 40% right with large winners is a
    good record and 60% right with large losers is a bad one. Reporting the count without the
    weight is how a ledger stays technically true and still tells you the wrong thing."""
    from tradeos import db, ledger
    with db.connect() as conn:
        o = ledger.summary(conn)["overall"]
    for key in ("avg_excess_on_hits", "avg_excess_on_misses", "expectancy"):
        assert key in o, f"{key} missing — a hit rate alone does not describe a record"


@needs_db
def test_the_two_planes_are_never_pooled_into_one_record():
    """The impact engine and the backtested smart-money signal are different subsystems with
    different results. Pooling them produced a marketing page that announced the product does not
    work, using a number that had never measured the product. Open work has to be attributable
    too, or a surface can only say "80 open" and not whose."""
    from tradeos import db, ledger
    with db.connect() as conn:
        s = ledger.summary(conn)
    origins = {r["key"] for r in s["open_by_origin"]}
    assert any(k.startswith("impact engine") for k in origins)
    assert any(k.startswith("signal plane") for k in origins)
    # Every resolved row is attributed to exactly one plane, so nothing hides in an aggregate.
    assert sum(r["n"] for r in s["by"]["origin"]) == s["overall"]["n"]


# ------------------------------------------------------------------ can the record tell "no edge"
#                                                                     from "not enough data"?
#
# The ledger published a -1.52% expectancy and a 41% hit rate as bare point estimates, and both the
# app and the marketing site read them as proof the signal failed. The mean's 95% interval spans
# zero: on this sample nothing is established either way. A track record that cannot say that is a
# vanity metric pointed the other way round.

def test_a_mean_whose_interval_spans_zero_is_not_significant():
    # Symmetric noise around a small negative mean — exactly the ledger's real situation.
    vals = [0.15, -0.13, 0.16, -0.14, 0.10, -0.12, 0.18, -0.20]
    out = ledger.mean_ci(vals)
    assert out["lo"] < 0 < out["hi"]
    assert out["significant"] is False


def test_a_real_effect_is_reported_as_significant():
    vals = [0.05, 0.06, 0.055, 0.048, 0.052, 0.058, 0.051, 0.049] * 4
    out = ledger.mean_ci(vals)
    assert out["lo"] > 0
    assert out["significant"] is True


def test_mean_ci_degrades_rather_than_dividing_by_zero():
    assert ledger.mean_ci([])["n"] == 0
    assert ledger.mean_ci([])["significant"] is False
    one = ledger.mean_ci([0.1])
    assert one["n"] == 1 and one["significant"] is False   # one call proves nothing


def test_proportion_z_measures_distance_from_a_coin_flip():
    assert ledger.proportion_z(115, 282) == pytest.approx(-3.10, abs=0.05)
    assert ledger.proportion_z(50, 100) == pytest.approx(0.0, abs=0.01)
    assert ledger.proportion_z(0, 0) is None


def test_sample_needed_says_what_it_would_take_to_know():
    """The number that turns "we cannot tell yet" from an excuse into a plan. At the 18% dispersion
    actually measured, a 1% per-call edge needs roughly 1,300-1,500 resolved calls."""
    n = ledger.sample_needed(0.183, 0.01)
    assert 1200 < n < 1600
    # A bigger edge is cheaper to prove.
    assert ledger.sample_needed(0.183, 0.03) < n
    assert ledger.sample_needed(0, 0.01) is None


@needs_db
def test_the_summary_publishes_the_interval_not_just_the_average():
    from tradeos import db
    with db.connect() as conn:
        o = ledger.summary(conn)["overall"]
    for key in ("expectancy_ci", "expectancy_significant", "hit_rate_z", "sample_for_1pct_edge"):
        assert key in o, f"{key} missing — a point estimate alone invites a verdict it cannot support"
    if o["expectancy_ci"][0] is not None:
        lo, hi = o["expectancy_ci"]
        assert lo <= o["expectancy"] <= hi
