"""Offline tests for Exposure — the surface that replaced the position tracker.

The rule these encode: a link is only drawn when it can be explained. "You are exposed to Asia" is
worthless; "two of your holdings have live claims naming Asia, here they are" is a statement the
reader can disagree with, which is the only kind worth showing.
"""
from tradeos import exposure

CLAIMS = [
    {"id": 1, "confidence": 0.8, "category": "trade_policy",
     "affected": [{"kind": "asset", "value": "NVDA", "direction": "down", "magnitude": "large"},
                  {"kind": "region", "value": "Asia", "direction": "down"}]},
    {"id": 2, "confidence": 0.5, "category": "energy",
     "affected": [{"kind": "commodity", "value": "Brent", "direction": "up"}]},
    {"id": 3, "confidence": 0.9, "category": "trade_policy",
     "affected": [{"kind": "asset", "value": "AMD", "direction": "up", "magnitude": "small"}]},
]


def test_only_claims_naming_a_holding_reach_you():
    out = exposure.claims_touching(CLAIMS, {"NVDA", "AMD"})
    assert {c["id"] for c in out} == {1, 3}


def test_a_reaching_claim_names_which_holding_carries_it():
    """Saying "this affects your portfolio" without saying which position is unfalsifiable."""
    out = exposure.claims_touching(CLAIMS, {"NVDA"})
    assert out[0]["your_holdings"] == [{"symbol": "NVDA", "direction": "down", "magnitude": "large"}]


def test_touching_claims_are_ordered_by_confidence():
    out = exposure.claims_touching(CLAIMS, {"NVDA", "AMD"})
    assert [c["id"] for c in out] == [3, 1]


def test_nothing_held_means_nothing_reaches_you():
    assert exposure.claims_touching(CLAIMS, set()) == []
    assert exposure.claims_touching([], {"NVDA"}) == []


def test_geographic_reach_records_the_path_not_just_the_country():
    reach = exposure.geographic_reach(CLAIMS, {"NVDA"})
    asia = [r for r in reach if r["country"] == "CN"]
    assert asia and "NVDA" in asia[0]["via"]


def test_a_claim_that_reaches_no_holding_contributes_no_geography():
    """Claim 2 names Brent but no held asset — its producers must not light up on your map."""
    reach = exposure.geographic_reach(CLAIMS, {"AMD"})
    assert "SA" not in {r["country"] for r in reach}


def test_corridors_need_a_home_country():
    """A corridor with one end missing is a line to nowhere."""
    reach = [{"country": "CN", "via": ["NVDA"], "claims": 1}]
    corridors = [{"from": "AE", "to": "CN", "direction": "import", "rank": 1, "weight": 1.0}]
    assert exposure.corridor_dependence(reach, corridors, None) == []
    assert len(exposure.corridor_dependence(reach, corridors, "AE")) == 1


def test_corridor_role_is_stated_from_the_readers_side():
    reach = [{"country": "CN", "via": ["NVDA"], "claims": 1}]
    out = exposure.corridor_dependence(
        reach, [{"from": "CN", "to": "AE", "direction": "export", "rank": 1, "weight": 1.0}], "AE")
    assert out[0]["role"] == "you import from"


def test_concentration_states_a_share_and_flags_only_the_large_ones():
    out = exposure.concentration(["energy", "energy", "energy", "tech"])
    energy = next(r for r in out if r["label"] == "energy")
    tech = next(r for r in out if r["label"] == "tech")
    assert energy["share"] == 0.75 and energy["notable"] is True
    assert tech["notable"] is False


def test_concentration_of_an_empty_list_is_empty_not_zero():
    assert exposure.concentration([]) == []


def test_summary_reads_correctly_when_nothing_reaches_you():
    s = exposure.summarise(["NVDA", "AMD"], [], [], [])
    assert s["with_live_claims"] == 0
    assert "None of your 2 holdings" in s["line"]


def test_summary_counts_distinct_holdings_not_claims():
    """Three claims about one holding is one exposed holding, not three."""
    many = [{"id": i, "your_holdings": [{"symbol": "NVDA"}]} for i in range(3)]
    s = exposure.summarise(["NVDA", "AMD"], many, [], [])
    assert s["with_live_claims"] == 1
