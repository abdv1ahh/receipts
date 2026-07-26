"""Offline tests for world context at trade time — the half of a journal a journal cannot see.

Three things these encode, in order of how badly getting them wrong would hurt:

  1. A missed symbol match makes the coach report agreement that was never there. The impact
     engine does not always write a bare ticker, so the matching is tested against the value
     shapes that are actually in the database.
  2. A pattern named from three trades is noise in the costume of insight. The sample floors are
     tested from both sides — that they hold, and that they release once the sample is real.
  3. The coach must stay constructive and must never promote a 41%-accurate machine to the
     arbiter of a human's decision.
"""
import pytest

from tradeos import journal_context as jc

# Shapes taken from real rows: the engine writes a bare ticker, a full company name with the ticker
# in parentheses, and prose that names no instrument at all.
CLAIMS = [
    {"id": 1, "confidence": 0.7, "horizon": "weeks", "headline": "Imax screenings",
     "novelty": 0.8, "affected": [{"kind": "asset", "value": "AMC Entertainment Holdings Inc. (AMC)",
                                   "direction": "up", "magnitude": "moderate"}]},
    {"id": 2, "confidence": 0.6, "horizon": "days", "headline": "Chip curbs", "novelty": 0.4,
     "affected": [{"kind": "asset", "value": "NVDA", "direction": "down"},
                  {"kind": "sector", "value": "semiconductors", "direction": "down"}]},
    {"id": 3, "confidence": 0.5, "horizon": "months", "headline": "Duration", "novelty": None,
     "affected": [{"kind": "asset", "value": "Treasury bonds", "direction": "down"}]},
]


# ------------------------------------------------------------------ naming an instrument

@pytest.mark.parametrize("value,expected", [
    ("NVDA", {"NVDA"}),
    ("$TSLA", {"TSLA"}),
    ("AMC Entertainment Holdings Inc. (AMC)", {"AMC"}),
    ("BRK.B", {"BRK.B"}),
    ("Treasury bonds", set()),
    ("the S&P 500", set()),
    ("", set()),
    (None, set()),
])
def test_ticker_extraction_matches_the_shapes_the_engine_actually_writes(value, expected):
    assert jc._symbols_named(value) == expected


def test_a_company_name_carrying_its_ticker_still_matches_the_trade():
    """The reason this rule exists: exact matching alone reports no disagreement when there was
    one, and a coach that misses disagreements is worse than one that has none to report."""
    on = jc.claims_on_symbol(CLAIMS, "AMC")
    assert [c["claim_id"] for c in on] == [1]
    assert on[0]["named_as"] == "AMC Entertainment Holdings Inc. (AMC)"


def test_only_an_asset_commits_to_a_direction_on_the_instrument():
    """A claim about semiconductors bears on an NVDA trade but did not commit to a direction on
    NVDA. Counting it would let the coach report a disagreement that was never made."""
    sector_only = [{"id": 9, "affected": [{"kind": "sector", "value": "NVDA", "direction": "up"}]}]
    assert jc.claims_on_symbol(sector_only, "NVDA") == []


def test_matching_is_case_insensitive_and_survives_whitespace():
    assert len(jc.claims_on_symbol(CLAIMS, "  nvda ")) == 1


def test_no_symbol_means_no_match_rather_than_everything():
    assert jc.claims_on_symbol(CLAIMS, None) == []
    assert jc.claims_on_symbol(CLAIMS, "") == []


def test_a_claim_naming_a_symbol_twice_is_counted_once():
    twice = [{"id": 4, "affected": [{"kind": "asset", "value": "AMC", "direction": "up"},
                                    {"kind": "asset", "value": "$AMC", "direction": "up"}]}]
    assert len(jc.claims_on_symbol(twice, "AMC")) == 1


# ------------------------------------------------------------------ alignment

@pytest.mark.parametrize("direction,claim_dir,expected", [
    ("long", "up", "with"),
    ("long", "down", "against"),
    ("short", "down", "with"),
    ("short", "up", "against"),
])
def test_alignment_reads_a_short_as_the_mirror_of_a_long(direction, claim_dir, expected):
    assert jc.alignment(direction, [{"direction": claim_dir}]) == expected


def test_alignment_is_mixed_when_live_reads_disagree_with_each_other():
    assert jc.alignment("long", [{"direction": "up"}, {"direction": "down"}]) == "mixed"


def test_nothing_live_on_the_name_is_none_not_against():
    """Most trades are made in silence. Reading an absence of coverage as a warning would make the
    coach alarmist about the ordinary case."""
    assert jc.alignment("long", []) == "none"
    assert jc.alignment("long", [{"direction": None}]) == "none"


# ------------------------------------------------------------------ the frozen snapshot

def _as_of():
    from datetime import UTC, datetime
    return datetime(2026, 7, 26, 12, 0, tzinfo=UTC)


def test_summarize_stores_a_sample_but_counts_everything_live():
    """"34 live reads, here are the 8 that mattered to you" is honest; silently reporting 8 is not."""
    many = [{"id": i, "affected": [], "novelty": 0.5} for i in range(20)]
    out = jc.summarize(many, {"symbol": "AMC", "direction": "long"}, _as_of(), limit=8)
    assert out["n_live"] == 20
    assert len(out["claim_ids"]) == 8
    assert len(out["snapshot"]["claims"]) == 8


def test_summarize_records_the_disagreement_and_who_made_it():
    out = jc.summarize(CLAIMS, {"symbol": "AMC", "direction": "short"}, _as_of())
    assert out["alignment"] == "against"
    assert out["n_on_symbol"] == 1
    assert out["snapshot"]["on_symbol"][0]["claim_id"] == 1


def test_mean_novelty_ignores_claims_that_have_none_rather_than_scoring_them_zero():
    """A cluster with no novelty score is unknown, not novelty zero. Treating it as zero would drag
    every quiet-day reading toward 'the news was breaking'."""
    out = jc.summarize(CLAIMS, {"symbol": "AMC", "direction": "long"}, _as_of())
    assert out["mean_novelty"] == pytest.approx((0.8 + 0.4) / 2)


def test_an_empty_radar_is_a_valid_snapshot_not_a_failure():
    out = jc.summarize([], {"symbol": "AMC", "direction": "long"}, _as_of())
    assert out["n_live"] == 0 and out["alignment"] == "none" and out["mean_novelty"] is None


def test_basis_is_carried_through_so_a_reconstruction_can_never_pass_as_live():
    out = jc.summarize(CLAIMS, {"symbol": "AMC", "direction": "long"}, _as_of(), basis="reconstructed")
    assert out["basis"] == "reconstructed"


# ------------------------------------------------------------------ behavioural patterns

def _rows(n, alignment="none", pnl=None, novelty=0.3):
    return [{"alignment": alignment, "realized_pnl_pct": pnl, "mean_novelty": novelty}
            for _ in range(n)]


def test_no_pattern_is_stated_below_the_sample_floor():
    assert jc.behavioural_patterns(_rows(jc.MIN_PATTERN_SAMPLE - 1, "against")) == []


def test_the_floor_releases_once_the_sample_is_real():
    out = jc.behavioural_patterns(_rows(jc.MIN_PATTERN_SAMPLE, "against"))
    assert any(p["key"] == "entered_against_a_live_read" for p in out)


def test_trades_without_context_never_enter_the_denominator():
    """Six trades of which two carry context is a two-trade sample, not a six-trade one."""
    rows = _rows(2, "against") + [{"realized_pnl_pct": 0.1} for _ in range(9)]
    assert jc.behavioural_patterns(rows) == []


def test_a_disagreement_cites_the_ledgers_own_record_alongside_it():
    """The system is not the benchmark. Reporting "you traded against a live claim" without its
    real hit rate would quietly promote a 41%-accurate machine to the arbiter of a human call."""
    out = jc.behavioural_patterns(_rows(6, "against"), ledger_hit_rate=0.408)
    p = next(p for p in out if p["key"] == "entered_against_a_live_read")
    assert "41%" in p["detail"]
    assert "not a verdict" in p["detail"]


def test_a_disagreement_states_no_rate_when_the_ledger_has_none_to_publish():
    """Below its own sample floor the Ledger publishes nothing, and the coach may not invent one."""
    out = jc.behavioural_patterns(_rows(6, "against"), ledger_hit_rate=None)
    p = next(p for p in out if p["key"] == "entered_against_a_live_read")
    assert "%" not in p["detail"]


def test_mixed_reads_count_as_a_disagreement_not_as_agreement():
    out = jc.behavioural_patterns(_rows(6, "mixed"))
    p = next(p for p in out if p["key"] == "entered_against_a_live_read")
    assert p["count"] == 6


def test_outcomes_are_contrasted_only_when_both_sides_clear_the_cohort_floor():
    """One side thin means no contrast — this is the small-sample claim the whole product refuses."""
    thin = (_rows(jc.MIN_COHORT, "with", pnl=0.1) + _rows(2, "against", pnl=-0.1))
    assert not any(p["key"] == "alignment_outcome_gap" for p in jc.behavioural_patterns(thin))


def test_outcomes_are_contrasted_once_both_cohorts_are_real():
    rows = (_rows(jc.MIN_COHORT, "with", pnl=0.1) + _rows(jc.MIN_COHORT, "against", pnl=-0.1))
    p = next(p for p in jc.behavioural_patterns(rows) if p["key"] == "alignment_outcome_gap")
    assert "agreed" in p["headline"]
    assert "not a rule" in p["detail"]


def test_an_all_quiet_journal_is_reported_as_its_own_state():
    out = jc.behavioural_patterns(_rows(6, "none"))
    assert [p["key"] for p in out] == ["traded_in_silence"]


def test_the_novelty_split_needs_both_sides_to_exist():
    """With every entry on a busy day there is no tendency to report, only a constant."""
    out = jc.behavioural_patterns(_rows(6, "none", novelty=0.9))
    assert not any(p["key"] == "entry_day_novelty" for p in out)


def test_the_novelty_split_reports_the_lean_when_both_sides_exist():
    rows = _rows(4, "with", novelty=0.9) + _rows(2, "with", novelty=0.2)
    p = next(p for p in jc.behavioural_patterns(rows) if p["key"] == "entry_day_novelty")
    assert p["count"] == 4 and p["of"] == 6


def test_no_pattern_is_ever_phrased_as_a_verdict_on_the_trader():
    """A coach that makes someone feel worse after a loss is a coach they stop opening, and then it
    helps nobody. Tone is a shipped requirement here, not a preference."""
    rows = (_rows(jc.MIN_COHORT, "with", pnl=0.1, novelty=0.9)
            + _rows(jc.MIN_COHORT, "against", pnl=-0.1, novelty=0.2))
    banned = ("mistake", "you should", "wrong", "bad ", "failed", "poor ", "avoid")
    for p in jc.behavioural_patterns(rows, ledger_hit_rate=0.408):
        text = f"{p['headline']} {p['detail']}".lower()
        assert p["tone"] in ("neutral", "positive"), p["key"]
        for word in banned:
            # "That is a disagreement, not a mistake" is the one licensed use, and it is a denial.
            assert word not in text or f"not a {word.strip()}" in text, f"{p['key']}: {word!r}"


def test_every_pattern_carries_its_own_sample_size():
    """A count without a denominator is a rhetorical device, not a measurement."""
    rows = _rows(4, "with", novelty=0.9) + _rows(4, "against", novelty=0.2)
    for p in jc.behavioural_patterns(rows, ledger_hit_rate=0.408):
        assert isinstance(p["count"], int) and isinstance(p["of"], int) and p["of"] > 0


# ------------------------------------------------------------------ the guarded prose path

def test_the_report_prose_renders_patterns_and_clears_the_directive_guard():
    from tradeos import insights
    from tradeos.explain.guards import directive_guard

    patterns = jc.behavioural_patterns(
        _rows(jc.MIN_COHORT, "with", pnl=0.1, novelty=0.9)
        + _rows(jc.MIN_COHORT, "against", pnl=-0.1, novelty=0.2), ledger_hit_rate=0.408)
    report = insights.build_report({"n_closed": 10, "sufficient": True, "win_rate": 0.5},
                                   [], 10, patterns, n_with_context=10)
    prose = insights.render_report(report)
    assert directive_guard(prose)
    assert patterns[0]["headline"] in prose


def test_report_numbers_all_trace_back_to_the_payload():
    """The deterministic prose is the fallback the model path is measured against; if it could not
    clear the numbers guard itself, a guard trip would have nowhere safe to land."""
    from tradeos import insights
    from tradeos.explain.guards import allowed_numbers, numbers_guard

    patterns = jc.behavioural_patterns(_rows(6, "against"), ledger_hit_rate=0.408)
    report = insights.build_report({"n_closed": 6, "sufficient": False}, [], 6, patterns, 6)
    prose = insights.render_report(report)
    assert numbers_guard(prose, allowed_numbers(report, {"_const": [1, 2, 5, 100]}))
