"""CoinGecko free-API client (Slice I) — real crypto market data, no key, ToS-clean.

Two fixed queries only (never an open proxy): top markets by cap, and search-trending coins. Host
allowlisted (SSRF defense) with a declared User-Agent, matching the SEC/FINRA/Tiingo/HN clients.
"""
from __future__ import annotations

import logging
from urllib.parse import urlparse

import httpx

log = logging.getLogger("tradeos.crypto.coingecko")

CG_HOST = "api.coingecko.com"
CG = "https://api.coingecko.com/api/v3"


def _client() -> httpx.Client:
    if urlparse(CG).hostname != CG_HOST:
        raise ValueError("CoinGecko host allowlist violation")
    return httpx.Client(timeout=20.0, headers={"User-Agent": "TradeOS (contact via app)"})


def top_markets(limit: int = 20) -> list[dict]:
    with _client() as c:
        r = c.get(f"{CG}/coins/markets", params={
            "vs_currency": "usd", "order": "market_cap_desc", "per_page": limit, "page": 1,
            "price_change_percentage": "24h"})
        r.raise_for_status()
        return r.json()


def fetch_trending() -> list[dict]:
    with _client() as c:
        r = c.get(f"{CG}/search/trending")
        r.raise_for_status()
        items = r.json().get("coins", [])
    out = []
    for it in items:
        coin = it.get("item", {})
        out.append({"id": coin.get("id"), "symbol": (coin.get("symbol") or "").upper(),
                    "name": coin.get("name"), "rank": coin.get("market_cap_rank")})
    return out
