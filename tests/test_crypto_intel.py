"""Offline tests for the crypto interpretation layer.

Most of these encode calibration decisions that were WRONG on first contact with live data, and
the comments say which — a threshold that fires on everything is as useless as one that never
fires, and both were shipped here before being measured.
"""
import pytest

from tradeos import crypto_intel as C
from tradeos.ingestion import derivatives as D


def pos(symbol="BTC", funding=0.0, long_share=0.65, direction="flat"):
    return {"symbol": symbol, "funding_rate": funding,
            "funding_annualised_pct": D.annualised(funding),
            "funding_direction": direction, "long_account_share": long_share,
            "open_interest": 100000.0}


# ------------------------------------------------------------------ the calibration that mattered

def test_a_structurally_long_retail_crowd_is_not_a_signal():
    """Measured live: all five majors showed 65-74% of accounts long AT ONCE, including DOGE while
    its funding was 0.06% a year. Retail perp accounts lean long nearly always. An earlier version
    OR-ed account share with funding and labelled all five "crowded long" — a reading that fires on
    everything says nothing."""
    r = C.read_positioning(pos(long_share=0.74, funding=0.0000002))
    assert r["state"] == "balanced"


def test_meaningful_funding_still_reads_as_leaning():
    """The opposite error: raising the threshold until Bitcoin paying ~6% a year read 'balanced'
    threw the signal away. The band has to discriminate, not just avoid false positives."""
    r = C.read_positioning(pos(funding=0.0000543))          # ~5.9% annualised
    assert r["state"] == "leaning long"


@pytest.mark.parametrize("annual_pct,expected", [
    (0.5, "balanced"), (1.9, "balanced"),
    (2.5, "leaning long"), (10.0, "leaning long"),
    (12.0, "crowded long"), (30.0, "crowded long"),
    (45.0, "extremely crowded long"),
])
def test_funding_bands_are_graded_not_binary(annual_pct, expected):
    funding = annual_pct / (3 * 365 * 100)
    assert C.read_positioning(pos(funding=funding))["state"] == expected


def test_negative_funding_reads_as_the_short_side():
    r = C.read_positioning(pos(funding=-0.0002))
    assert r["state"].endswith("short") and "paying longs" in r["mechanism"]


# ------------------------------------------------------------------ falsifiability

def test_every_reading_carries_an_invalidation_condition():
    """A reading you cannot be wrong about is worthless, and this product scores itself."""
    for annual in (-45.0, -5.0, 0.0, 5.0, 45.0):
        r = C.read_positioning(pos(funding=annual / (3 * 365 * 100)))
        assert r["invalidation"] and "breaks if" in r["invalidation"]


def test_a_reading_needs_funding_data_and_stays_silent_without_it():
    """Silence beats a manufactured reading."""
    assert C.read_positioning({"symbol": "BTC", "funding_rate": None}) is None


# ------------------------------------------------------------------ honesty about meme assets

def test_attention_driven_assets_are_named_as_such():
    r = C.read_positioning(pos(symbol="DOGE"))
    assert r["attention_driven"] is True
    assert any("no cash flows" in n for n in r["notes"])


def test_a_major_is_not_labelled_attention_driven():
    assert C.read_positioning(pos(symbol="BTC"))["attention_driven"] is False


# ------------------------------------------------------------------ liquidity

def test_liquidity_reads_expansion_and_contraction():
    growing = C.liquidity([{"market_cap": 1e11, "change_24h": 0.9}])
    shrinking = C.liquidity([{"market_cap": 1e11, "change_24h": -0.9}])
    assert growing["state"] == "expanding" and shrinking["state"] == "contracting"


def test_liquidity_says_it_is_fuel_not_direction():
    """Stablecoin supply says buying power exists, never that it will be used."""
    assert "not direction" in C.liquidity([{"market_cap": 1e11, "change_24h": 0.9}])["mechanism"]


def test_liquidity_is_unavailable_rather_than_zero_without_data():
    out = C.liquidity([])
    assert out["available"] is False and "not read" in out["note"]


# ------------------------------------------------------------------ funding maths

def test_annualised_makes_a_tiny_rate_legible():
    """0.01% per 8-hour period is ~11% a year. Showing the raw figure is how a real cost is missed."""
    assert D.annualised(0.0001) == pytest.approx(10.95, abs=0.01)
    assert D.annualised(None) is None


def test_funding_trend_detects_building_and_unwinding():
    building = D.funding_trend([{"fundingRate": "0.00001"}] * 6 + [{"fundingRate": "0.0002"}])
    unwinding = D.funding_trend([{"fundingRate": "0.0002"}] * 6 + [{"fundingRate": "0.00001"}])
    assert building["direction"] == "building"
    assert unwinding["direction"] in ("unwinding", "flat")


def test_funding_trend_is_safe_on_empty_history():
    assert D.funding_trend([])["direction"] == "unknown"


# ------------------------------------------------------------------ summary

def test_summary_names_the_strongest_rather_than_listing_everything():
    readings = [C.read_positioning(pos(symbol=s, funding=f / (3 * 365 * 100)))
                for s, f in (("BTC", 20.0), ("ETH", 3.0), ("SOL", 0.2))]
    line = C.structure_summary(readings, {"available": False})["line"]
    assert "BTC" in line and "20.0% a year" in line


def test_summary_states_the_absence_of_crowding_plainly():
    readings = [C.read_positioning(pos(symbol=s, funding=0.0)) for s in ("BTC", "ETH")]
    assert "not crowded" in C.structure_summary(readings, {"available": False})["line"]
