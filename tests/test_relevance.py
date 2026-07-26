"""Offline tests for personal relevance — the thing that makes the same event read differently
from Sharjah than from São Paulo. No network, no model: relevance must work when inference is
down, because an unranked feed is useless and a fabricated ranking is worse.
"""
import pytest

from tradeos import relevance

AE = next(c for c in relevance.COUNTRIES if c["country"] == "AE")
BR = next(c for c in relevance.COUNTRIES if c["country"] == "BR")
US = next(c for c in relevance.COUNTRIES if c["country"] == "US")


# ------------------------------------------------------------------ reference data integrity

def test_every_country_row_is_complete_and_sourced():
    """These are stated facts, not estimates. A row without a source is a guess."""
    for c in relevance.COUNTRIES:
        assert len(c["country"]) == 2 and c["country"].isupper()
        assert len(c["currency"]) == 3
        assert c["source"], f"{c['country']} has no source"
        assert c["export_partners"] and c["import_partners"]
        assert c["currency_regime"] in ("floating", "managed", "pegged_usd", "pegged_eur")


def test_a_pegged_currency_names_what_it_is_pegged_to():
    for c in relevance.COUNTRIES:
        if c["currency_regime"].startswith("pegged"):
            assert c["pegged_to"], f"{c['country']} is pegged but names no anchor"


def test_partner_codes_are_well_formed():
    for c in relevance.COUNTRIES:
        for code in c["export_partners"] + c["import_partners"]:
            assert len(code) == 2 and code.isupper(), f"{c['country']}: bad partner code {code!r}"


# ------------------------------------------------------------------ geography

def test_your_own_country_scores_highest():
    assert relevance.geo_weight("AE", AE, ["AE"]) == 1.0


def test_a_top_trade_partner_outscores_a_minor_one():
    """AE's export partners are India, Saudi, Japan, China, Iraq — in that order."""
    top = relevance.geo_weight("AE", AE, ["IN"])
    minor = relevance.geo_weight("AE", AE, ["IQ"])
    assert top > minor > 0.3


def test_an_unrelated_country_still_scores_above_zero():
    """A world-event product that only surfaces domestic news is a local newspaper."""
    assert relevance.geo_weight("AE", AE, ["NZ"]) > 0


def test_the_same_event_reads_differently_from_two_countries():
    """The premise of the whole product, as one assertion.

    India is the UAE's largest export market and only Brazil's fifth-largest supplier, so an event
    in India should matter measurably more to a reader in Sharjah than to one in São Paulo."""
    india_event = ["IN"]
    from_uae = relevance.geo_weight("AE", AE, india_event)
    from_brazil = relevance.geo_weight("BR", BR, india_event)
    assert from_uae > from_brazil


def test_an_unplaced_event_is_mildly_relevant_to_everyone():
    assert relevance.geo_weight("AE", AE, []) == 0.3


def test_a_reader_with_no_country_set_still_gets_a_usable_score():
    assert 0 < relevance.geo_weight(None, None, ["US"]) < 1.0


# ------------------------------------------------------------------ currency

def test_a_claim_about_your_peg_anchor_is_almost_your_own_monetary_policy():
    """AED is pegged to USD, so a USD claim transmits almost fully. A US-centric feed drops this."""
    usd_claim = [{"kind": "currency", "value": "USD", "direction": "up"}]
    assert relevance.currency_weight(AE, usd_claim) == 0.9


def test_a_claim_about_your_own_currency_scores_full():
    assert relevance.currency_weight(AE, [{"kind": "currency", "value": "AED", "direction": "down"}]) == 1.0


def test_a_floating_currency_has_no_peg_bonus():
    usd_claim = [{"kind": "currency", "value": "EUR", "direction": "up"}]
    assert relevance.currency_weight(US, usd_claim) == 0.2


def test_a_claim_naming_no_currency_contributes_nothing():
    assert relevance.currency_weight(AE, [{"kind": "asset", "value": "XOM", "direction": "up"}]) == 0.0


# ------------------------------------------------------------------ watchlist

def test_a_claim_touching_your_watchlist_outscores_one_that_does_not():
    affected = [{"kind": "asset", "value": "NVDA", "direction": "up"}]
    assert relevance.watchlist_weight(affected, {"NVDA"}) > relevance.watchlist_weight(affected, {"AAPL"})


def test_more_watchlist_hits_score_higher():
    two = [{"kind": "asset", "value": "NVDA"}, {"kind": "asset", "value": "AMD"}]
    one = [{"kind": "asset", "value": "NVDA"}]
    assert relevance.watchlist_weight(two, {"NVDA", "AMD"}) > relevance.watchlist_weight(one, {"NVDA", "AMD"})


def test_an_empty_watchlist_does_not_zero_the_whole_feed():
    """A new user has no watchlist. Their feed must still rank."""
    assert relevance.watchlist_weight([{"kind": "asset", "value": "NVDA"}], set()) > 0


# ------------------------------------------------------------------ the combined score

def _claim(**kw):
    return {"confidence": 0.7, "affected": [{"kind": "asset", "value": "XOM", "direction": "up"}],
            "geo": ["AE"], **kw}


def test_score_is_bounded_and_explains_itself():
    out = relevance.score(_claim(), {"country": "AE"}, AE, {"XOM"}, novelty=0.8)
    assert 0.0 <= out["relevance"] <= 1.0
    assert set(out["parts"]) == {"confidence", "watchlist", "geo", "currency", "novelty"}


def test_a_relevant_claim_outranks_an_irrelevant_one_for_the_same_reader():
    mine = relevance.score(_claim(geo=["AE"]), {"country": "AE"}, AE, {"XOM"}, novelty=0.9)
    theirs = relevance.score(_claim(geo=["NZ"], affected=[{"kind": "asset", "value": "ZZZ",
                                                          "direction": "up"}]),
                             {"country": "AE"}, AE, {"XOM"}, novelty=0.2)
    assert mine["relevance"] > theirs["relevance"]


def test_low_confidence_lowers_relevance_all_else_equal():
    high = relevance.score(_claim(confidence=0.9), {"country": "AE"}, AE, {"XOM"}, novelty=0.5)
    low = relevance.score(_claim(confidence=0.1), {"country": "AE"}, AE, {"XOM"}, novelty=0.5)
    assert high["relevance"] > low["relevance"]


def test_score_works_with_no_profile_at_all():
    """Relevance must degrade, not crash, for a logged-out or un-onboarded reader."""
    out = relevance.score(_claim(), None, None, None, None)
    assert 0.0 <= out["relevance"] <= 1.0


@pytest.mark.parametrize("dominant,expected_fragment", [
    ("watchlist", "watchlist"), ("geo", "where it happened"), ("currency", "your currency"),
])
def test_explain_names_the_biggest_reason(dominant, expected_fragment):
    parts = {"confidence": 0.1, "watchlist": 0.1, "geo": 0.1, "currency": 0.1, "novelty": 0.1}
    parts[dominant] = 0.99
    assert expected_fragment in relevance.explain(parts)


def test_an_import_partner_is_ranked_within_its_own_list():
    """Concatenating the export and import lists offset every import partner by the length of the
    export list, so a country's LARGEST supplier scored as if it were its sixth-largest customer.
    AE imports most from China and exports most to India — both should rank as top partners."""
    top_customer = relevance.geo_weight("AE", AE, ["IN"])   # #1 export partner
    top_supplier = relevance.geo_weight("AE", AE, ["CN"])   # #1 import partner
    assert top_supplier == top_customer == 0.75


def test_explain_never_gives_a_zero_weighted_reason():
    """Telling a reader an item was shown because it 'touches your currency' when it names no
    currency is a small lie. This product does not get to tell small ones."""
    parts = {"confidence": 0.0, "watchlist": 0.0, "geo": 0.0, "currency": 0.0, "novelty": 0.5}
    assert "genuinely new" in relevance.explain(parts)
    assert "currency" not in relevance.explain(parts)


def test_explain_is_deterministic_on_a_tie():
    """max() over a dict returns insertion order on ties, which made the stated reason depend on
    dict ordering rather than on anything real."""
    tied = {"confidence": 0.5, "watchlist": 0.5, "geo": 0.5, "currency": 0.5, "novelty": 0.5}
    assert relevance.explain(tied) == relevance.explain(dict(reversed(list(tied.items()))))
    assert "watchlist" in relevance.explain(tied)      # most specific reason wins a tie


def test_explain_degrades_when_nothing_scored():
    assert "general feed" in relevance.explain(dict.fromkeys(("confidence", "watchlist", "geo", "currency", "novelty"), 0.0))


# ------------------------------------------------------------------ what a claim is ABOUT (Phase 7)

def test_relevance_places_a_claim_by_what_it_affects_not_who_published_it():
    """The single most repeated mistake in this project, found a fourth time — in the ranking.

    `geo` on an event is where the OUTLET sits: the news adapter marks every US-markets item `US`,
    so a US wire filing about Asian exporters was scored as a US event. `geography.countries_for`
    exists precisely to fix this and was honoured by the globe and by Exposure but not by
    relevance, which meant a reader in Tokyo and a reader in São Paulo saw nearly the same order.
    """
    us_wire_about_asia = {"confidence": 0.7, "geo": ["US"],
                          "affected": [{"kind": "region", "value": "Asia", "direction": "down"}]}
    assert "JP" in relevance.places(us_wire_about_asia)
    assert relevance.places(us_wire_about_asia) != ["US"]


def test_the_outlet_country_is_used_only_when_nothing_else_maps():
    """A last resort, not a default — an unplaceable claim is better than a wrongly placed one."""
    unmappable = {"geo": ["GB"], "affected": [{"kind": "asset", "value": "NVDA"}]}
    assert relevance.places(unmappable) == ["GB"]
    assert relevance.places({"geo": [], "affected": []}) == []


def test_the_same_claim_ranks_differently_from_two_countries():
    """The personalisation promise, asserted rather than assumed. Before the fix above these two
    scored within a rounding of each other, because both were really scoring the publisher."""
    gulf_story = {"confidence": 0.7,
                  "geo": ["US"],                       # filed by a US outlet
                  "affected": [{"kind": "region", "value": "Middle East", "direction": "down"}]}
    ae = relevance.score(gulf_story, {"country": "AE"}, AE)
    br = relevance.score(gulf_story, {"country": "BR"}, BR)
    assert ae["relevance"] > br["relevance"]
    assert ae["parts"]["geo"] == 1.0                   # it happened where the reader is
