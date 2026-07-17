"""Slice 5 offline tests for the explanation guards and the deterministic template.

The guards are security controls (docs/threat-models/explanation.md): the model may never
introduce a number the computation didn't produce, nor emit directive/advice language. These
tests include the exact cases Feature Spec 5.5 requires — a 'you should buy' output and a
hit-rate the payload never contained both force the template.
"""
from tradeos.explain import template
from tradeos.explain.guards import allowed_numbers, base_rate_integrity_guard, directive_guard, numbers_guard

DETAIL = {
    "cluster_id": 1, "issuer_entity": 862, "symbol": "ELAN", "name": "Elanco Animal Health Inc",
    "cik": "1739104", "score": 4.95, "confidence_bucket": "medium", "voices": 8,
    "source_classes": ["activist", "insider", "passive_stake"], "definition_version": 2,
    "inputs": {
        "window_days": 90, "definition_version": 2,
        "liquidity_floor": {"ok": True, "basis": "exchange_listing"},
        "freshest_knowable": "2026-07-14T20:00:00+00:00",
        "stalest_knowable": "2026-07-07T13:00:00+00:00",
        "contributions": [
            {"source_class": "insider", "subtype": "insider_purchase", "voice": "insider:1",
             "knowable_time": "2026-07-09T00:00:00+00:00", "magnitude": 100000, "decayed_weight": 0.66},
            {"source_class": "activist", "subtype": "stake_13d_amend", "voice": "filer:10",
             "knowable_time": "2026-07-14T00:00:00+00:00", "magnitude": None, "decayed_weight": 0.78},
            {"source_class": "passive_stake", "subtype": "stake_13g", "voice": "filer:20",
             "knowable_time": "2026-07-10T00:00:00+00:00", "magnitude": None, "decayed_weight": 0.60},
        ],
        "context": [],
    },
}
CAL = {
    "per_bucket": {
        "medium": {"30": {"episodes": 27, "sufficient": False, "hit_rate": None, "ci95": None}},
        "low": {"30": {"episodes": 107, "sufficient": True, "hit_rate": 0.55, "ci95": [0.457, 0.642]}},
    },
    "horizons": [30, 90, 180],
}


# ------------------------------------------------------------------ directive guard

def test_directive_guard_blocks_advice():
    assert directive_guard("You should buy ELAN now") is False
    assert directive_guard("We recommend a position in this name") is False
    assert directive_guard("Analysts set a strong buy with a price target") is False
    assert directive_guard("Consider going long here") is False


def test_directive_guard_allows_description():
    ok = ("Eight independent sources converged; an insider purchased shares and an activist "
          "increased its stake. This describes disclosed activity, not a recommendation.")
    assert directive_guard(ok) is True


# ------------------------------------------------------------------- numbers guard

def test_numbers_guard_blocks_invented_figure():
    allowed = allowed_numbers(DETAIL, CAL)
    # payload never contains a 75% hit rate -> guard must reject (Spec 5.5 case)
    assert numbers_guard("Backtested 75% of the time across 40 episodes", allowed) is False


def test_numbers_guard_allows_payload_numbers_and_formats():
    allowed = allowed_numbers(DETAIL, CAL)
    assert numbers_guard("8 sources converged for a score of 4.95 over 90 days", allowed) is True
    assert numbers_guard("across 27 episodes", allowed) is True          # from calibration
    assert numbers_guard("a 55% base rate", allowed) is True             # 0.55 -> 55%
    assert numbers_guard("filed on 2026-07-14", allowed) is True         # year + payload date


# --------------------------------------------------------------------- template

def test_template_is_deterministic_and_guard_clean():
    a = template.render(DETAIL, CAL["per_bucket"]["medium"]["30"], 30)
    b = template.render(DETAIL, CAL["per_bucket"]["medium"]["30"], 30)
    assert a == b
    # the template itself must never trip either guard
    assert directive_guard(a) is True
    assert numbers_guard(a, allowed_numbers(DETAIL, CAL)) is True
    # it states the honest qualifier and the insufficient-sample base rate
    assert "not a prediction about any position" in a
    assert "27 episodes" in a


def test_base_rate_integrity_guard():
    """Feature Spec 5.5: a stated rate must match the record; no rate may be stated on a thin
    sample; changing the payload's 55 to 75 forces the template."""
    sufficient = {"episodes": 134, "sufficient": True, "hit_rate": 0.55}
    insufficient = {"episodes": 18, "sufficient": False, "hit_rate": None}
    assert base_rate_integrity_guard("followed by positive excess 55% of the time", sufficient) is True
    assert base_rate_integrity_guard("hit 75% of the time", sufficient) is False          # divergent rate
    assert base_rate_integrity_guard("40% of the time", insufficient) is False            # rate on thin sample
    assert base_rate_integrity_guard("insufficient historical sample to state a base rate", insufficient) is True


def test_template_states_real_rate_when_sufficient():
    low = dict(DETAIL, confidence_bucket="low")
    prose = template.render(low, CAL["per_bucket"]["low"]["30"], 30)
    assert "55% of the time at 30 days" in prose
    assert "across 107 episodes" in prose
