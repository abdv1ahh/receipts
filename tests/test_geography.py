"""Offline tests for placing events on a map.

The rule that matters most: a wrong country is worse than no country. An event on the wrong part
of the world is a confident lie; an absent one is a visible gap. So every function here returns
nothing rather than guessing, and these tests exist mostly to hold that line.
"""
import pytest

from tradeos import geography

# ------------------------------------------------------------------ regions

@pytest.mark.parametrize("region,expected", [
    ("North America", "US"), ("north america", "CA"), ("Asia", "CN"),
    ("Middle East", "AE"), ("Europe", "DE"), ("GCC", "QA"), ("Emerging Markets", "BR"),
])
def test_regions_expand_to_countries(region, expected):
    assert expected in geography.countries_for([{"kind": "region", "value": region}])


def test_longest_region_match_wins():
    """"south america" must not be resolved by a shorter key that happens to be a substring."""
    south = geography.countries_for([{"kind": "region", "value": "South America"}])
    assert "BR" in south and "US" not in south


def test_global_places_an_event_nowhere():
    """"Global" is not a location. Lighting every country for it would be noise, not information."""
    assert geography.countries_for([{"kind": "region", "value": "global"}]) == []
    assert geography.countries_for([{"kind": "region", "value": "worldwide"}]) == []


def test_an_unknown_region_yields_nothing_rather_than_a_guess():
    assert geography.countries_for([{"kind": "region", "value": "Ruritania"}]) == []


# ------------------------------------------------------------------ currencies and commodities

def test_a_currency_places_an_event_in_its_issuer():
    assert geography.countries_for([{"kind": "currency", "value": "JPY"}]) == ["JP"]
    assert geography.countries_for([{"kind": "currency", "value": "aed"}]) == ["AE"]


def test_the_euro_places_an_event_across_the_bloc():
    out = geography.countries_for([{"kind": "currency", "value": "EUR"}])
    assert "DE" in out and "FR" in out


def test_a_commodity_places_an_event_with_its_producers():
    oil = geography.countries_for([{"kind": "commodity", "value": "Brent Crude Oil"}])
    assert "SA" in oil or "AE" in oil


def test_unknown_currencies_and_commodities_place_nothing():
    assert geography.countries_for([{"kind": "currency", "value": "XYZ"}]) == []
    assert geography.countries_for([{"kind": "commodity", "value": "unobtanium"}]) == []


# ------------------------------------------------------------------ shape and safety

def test_assets_and_sectors_do_not_place_an_event():
    """A ticker is not a location. Guessing a company's country from its symbol would be exactly
    the kind of confident invention this module exists to avoid."""
    assert geography.countries_for([{"kind": "asset", "value": "NVDA"},
                                    {"kind": "sector", "value": "manufacturing"}]) == []


def test_countries_are_deduplicated_and_order_is_stable():
    out = geography.countries_for([{"kind": "currency", "value": "USD"},
                                   {"kind": "region", "value": "North America"}])
    assert out == ["US", "CA", "MX"]                  # USD first, then the rest of the region


def test_empty_and_malformed_input_is_safe():
    assert geography.countries_for([]) == []
    assert geography.countries_for(None) == []
    assert geography.countries_for([{}, {"kind": "region"}, {"value": "Asia"}]) == []


# ------------------------------------------------------------------ corridors

EXPOSURE = [
    {"country": "AE", "export_partners": ["IN", "SA", "JP"], "import_partners": ["CN", "IN"]},
    {"country": "IN", "export_partners": ["US", "AE"], "import_partners": ["CN", "AE"]},
    {"country": "CN", "export_partners": ["US", "JP"], "import_partners": ["KR", "AU"]},
]


def test_corridors_only_connect_countries_we_can_describe_from_both_ends():
    """An arc to a country with no exposure row cannot be explained when clicked, so it is not
    drawn. A map full of unexplainable lines is decoration."""
    out = geography.corridors(EXPOSURE)
    known = {"AE", "IN", "CN"}
    for k in out:
        assert k["from"] in known and k["to"] in known
    assert not any(k["to"] in ("US", "JP", "KR", "AU") for k in out)


def test_a_top_partner_draws_heavier_than_a_minor_one():
    """An unweighted corridor map is a hairball. AE's #1 export market (India) must draw heavier
    than its #2 supplier (also India, but second in that list)."""
    out = geography.corridors(EXPOSURE)
    top = next(k for k in out if k["from"] == "AE" and k["to"] == "IN" and k["direction"] == "export")
    minor = next(k for k in out if k["from"] == "AE" and k["to"] == "IN" and k["direction"] == "import")
    assert top["rank"] == 1 and minor["rank"] == 2
    assert top["weight"] > minor["weight"] > 0.15


def test_no_country_trades_with_itself_and_no_duplicate_arcs():
    out = geography.corridors(EXPOSURE + [{"country": "AE", "export_partners": ["AE"],
                                           "import_partners": ["AE"]}])
    assert not any(k["from"] == k["to"] for k in out)
    keys = [(k["from"], k["to"], k["direction"]) for k in out]
    assert len(keys) == len(set(keys))


def test_corridor_weights_stay_in_a_drawable_range():
    for k in geography.corridors(EXPOSURE):
        assert 0.15 <= k["weight"] <= 1.0


def test_corridors_handle_an_empty_world():
    assert geography.corridors([]) == []


# ------------------------------------------------------------------ coverage honesty

def test_coverage_states_reach_rather_than_implying_completeness():
    c = geography.coverage({"US": 6, "AE": 1}, known_countries=10)
    assert c["countries_with_activity"] == 2
    assert c["placed_events"] == 7
    assert "no coverage yet, not a quiet one" in c["note"]


def test_coverage_of_an_empty_map_is_still_honest():
    c = geography.coverage({}, known_countries=10)
    assert c["countries_with_activity"] == 0 and c["placed_events"] == 0 and c["note"]
