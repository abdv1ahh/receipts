"""Crypto market data (Slice I) from CoinGecko's free API — real prices/24h moves/volume and
search-trending coins, with unmissable risk labeling (the master brief's mandate for crypto/meme
coins). This is displayed market data and attention, never advice, and it is entirely separate from
the hash-locked convergence signal. A short in-process cache bounds outbound calls; a fetch failure
degrades to an honest error, never a fabricated or stale-as-fresh price.

Pure formatting/labeling first, then the cached fetch orchestrator.
"""
from __future__ import annotations

import time

_CACHE: dict = {}
_TTL = 60.0                       # seconds; bounds calls to the free API regardless of traffic
HIGH_VOL_PCT = 20.0
MICROCAP_USD = 100_000_000
THIN_VOLUME_RATIO = 0.01


def risk_flags(coin: dict) -> list[str]:
    """Unmissable, honest risk labels for a coin — descriptive, never a recommendation."""
    flags = []
    chg = coin.get("price_change_percentage_24h")
    if chg is not None and abs(chg) >= HIGH_VOL_PCT:
        flags.append("high_volatility")
    mc = coin.get("market_cap")
    if mc and mc < MICROCAP_USD:
        flags.append("microcap")
    vol = coin.get("total_volume")
    if mc and vol is not None and vol / mc < THIN_VOLUME_RATIO:
        flags.append("thin_volume")
    return flags


def format_market(coin: dict) -> dict:
    # Thin the ~168 hourly sparkline points to a compact ~42 for a light client payload.
    spark = ((coin.get("sparkline_in_7d") or {}).get("price")) or []
    spark = spark[::4] if len(spark) > 48 else spark
    return {"id": coin.get("id"), "symbol": (coin.get("symbol") or "").upper(),
            "name": coin.get("name"), "price": coin.get("current_price"),
            "change_1h": coin.get("price_change_percentage_1h_in_currency"),
            "change_24h": coin.get("price_change_percentage_24h"),
            "change_7d": coin.get("price_change_percentage_7d_in_currency"),
            "market_cap": coin.get("market_cap"), "volume": coin.get("total_volume"),
            "rank": coin.get("market_cap_rank"), "risk": risk_flags(coin),
            "sparkline": [round(float(x), 6) for x in spark if x is not None]}


def _cache_get(key):
    v = _CACHE.get(key)
    return v[1] if v and time.time() - v[0] < _TTL else None


def _cache_put(key, data):
    _CACHE[key] = (time.time(), data)


def markets(limit: int = 20) -> list[dict]:
    key = f"markets:{limit}"
    hit = _cache_get(key)
    if hit is not None:
        return hit
    from .ingestion.coingecko import top_markets
    data = [format_market(c) for c in top_markets(limit)]
    _cache_put(key, data)
    return data


def trending() -> list[dict]:
    hit = _cache_get("trending")
    if hit is not None:
        return hit
    from .ingestion.coingecko import fetch_trending
    data = fetch_trending()
    _cache_put("trending", data)
    return data
