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
    assert set(out["parts"]) == {"confidence", "watchlist", "geo", "currency", "novelty",
                                 "authority", "commodity"}


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


# ------------------------------------------------------------------ authority (consequential accounts)
#
# `author_influence` is a stated editorial weight carried on an event by the consequential-accounts
# list. It reached the events table and was then read by nothing for the whole build; these hold the
# wiring in place.

def test_a_claim_with_no_author_is_neither_boosted_nor_penalised():
    """Most claims have no byline — a filing is not "said by" anyone in the sense this measures.
    Scoring an absence would push every SEC-derived interpretation down for no reason."""
    assert relevance.authority_weight({}) == relevance.NEUTRAL_AUTHORITY
    assert relevance.authority_weight({"author_influence": None}) == relevance.NEUTRAL_AUTHORITY


def test_a_more_consequential_voice_outranks_a_less_consequential_one():
    wire = relevance.score(_claim(author_influence=0.85), {"country": "AE"}, AE, {"XOM"}, novelty=0.5)
    blog = relevance.score(_claim(author_influence=0.2), {"country": "AE"}, AE, {"XOM"}, novelty=0.5)
    assert wire["relevance"] > blog["relevance"]


def test_authority_is_clamped_and_never_crashes_on_a_bad_value():
    assert relevance.authority_weight({"author_influence": 4}) == 1.0
    assert relevance.authority_weight({"author_influence": -3}) == 0.0


def test_authority_moves_the_score_less_than_what_the_claim_actually_says():
    """Who said it is evidence, not a substitute for the content. A maximally authoritative source
    must not outrank a claim that genuinely touches the reader's watchlist."""
    loud_but_irrelevant = relevance.score(
        _claim(author_influence=1.0, affected=[{"kind": "asset", "value": "ZZZ", "direction": "up"}]),
        {"country": "AE"}, AE, {"XOM"}, novelty=0.5)
    quiet_but_relevant = relevance.score(
        _claim(author_influence=0.0), {"country": "AE"}, AE, {"XOM"}, novelty=0.5)
    assert quiet_but_relevant["relevance"] > loud_but_irrelevant["relevance"]


def test_explain_never_cites_authority_for_an_unauthored_claim():
    """The neutral default must not produce "shown because of who reported it" on a claim that has
    no author at all — that would be the interface inventing a reason."""
    out = relevance.score(_claim(), {"country": "AE"}, AE, {"XOM"}, novelty=0.99)
    assert "who reported it" not in relevance.explain(out["parts"])


# ------------------------------------------------------------------ commodities are a relationship,
#                                                                     not a location
#
# The flagship promise is that the same day reads differently from different places. It did not.
# COMMODITY_COUNTRIES["oil"] lists six producers, `places()` treated all six as the event's
# LOCATION, and geo_weight returns 1.0 when your country is in that list — so a Gulf oil story
# scored identically, to four decimal places, for a reader in Abu Dhabi and one in Sao Paulo.

OIL_CLAIM = {"affected": [{"kind": "commodity", "value": "Brent Crude Oil"},
                          {"kind": "sector", "value": "Defense"}],
             "confidence": 0.7, "geo": None}


def test_a_commodity_no_longer_pretends_to_be_a_location():
    """Six oil producers are not six places an event happened."""
    assert relevance.places(OIL_CLAIM) == []


def test_a_region_still_places_an_event():
    claim = {"affected": [{"kind": "region", "value": "Middle East"}]}
    assert relevance.places(claim), "a region must still locate an event"


def test_the_same_oil_story_ranks_differently_in_the_uae_and_brazil():
    """Both are oil exporters and both are in the oil producer list. Crude is the UAE's FIRST
    export and Brazil's third, behind soybeans and iron ore — so it should not weigh the same."""
    uae = relevance.score(OIL_CLAIM, {"country": "AE"}, AE, set(), 0.76)
    brazil = relevance.score(OIL_CLAIM, {"country": "BR"}, BR, set(), 0.76)
    assert uae["relevance"] != brazil["relevance"], "personalisation is not personalising"
    assert uae["relevance"] > brazil["relevance"]


def test_commodity_weight_ranks_by_how_central_the_commodity_is():
    assert relevance.commodity_weight(AE, ["oil"]) > relevance.commodity_weight(BR, ["oil"])
    # Producing something outranks importing it.
    assert relevance.commodity_weight(BR, ["soybeans"]) > relevance.commodity_weight(BR, ["oil"])


def test_commodity_weight_is_zero_for_a_reader_with_no_exposure_data():
    assert relevance.commodity_weight(None, ["oil"]) == 0.0
    assert relevance.commodity_weight(AE, []) == 0.0


def test_explain_never_credits_a_commodity_a_reader_has_no_exposure_to():
    out = relevance.score(OIL_CLAIM, {"country": "JP"}, None, set(), 0.5)
    assert "your economy runs on" not in relevance.explain(out["parts"])
