"""Offline tests for the crypto layer's pure logic: honest risk labeling (high volatility, microcap,
thin volume) and market-row formatting. No network, no database."""
from tradeos import crypto as X


def test_risk_flags_high_volatility_and_microcap_and_thin_volume():
    coin = {"price_change_percentage_24h": 35.0, "market_cap": 40_000_000, "total_volume": 100_000}
    flags = X.risk_flags(coin)
    assert "high_volatility" in flags and "microcap" in flags and "thin_volume" in flags


def test_risk_flags_clean_large_cap_has_none():
    coin = {"price_change_percentage_24h": 2.1, "market_cap": 900_000_000_000, "total_volume": 30_000_000_000}
    assert X.risk_flags(coin) == []


def test_risk_flags_tolerates_missing_fields():
    assert X.risk_flags({}) == []
    assert "high_volatility" in X.risk_flags({"price_change_percentage_24h": -28.0})


def test_format_market_shapes_the_row():
    coin = {"id": "bitcoin", "symbol": "btc", "name": "Bitcoin", "current_price": 65000,
            "price_change_percentage_24h": 1.2, "market_cap": 1_280_000_000_000,
            "total_volume": 25_000_000_000, "market_cap_rank": 1}
    m = X.format_market(coin)
    assert m["symbol"] == "BTC" and m["price"] == 65000 and m["rank"] == 1 and m["risk"] == []
