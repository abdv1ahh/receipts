"""Binance public derivatives data — positioning, not price.

Price is the one thing every crypto site already shows, which is why the old Crypto surface was
worth nothing: a mirror of numbers anyone can get free elsewhere. What is much harder to find, and
what actually explains moves, is POSITIONING — who is leveraged which way, how crowded it is, and
whether that crowd is building or unwinding.

These endpoints are public and need no key (verified 2026-07-25):

  premiumIndex                    the current funding rate and mark price
  fundingRate                     the funding history, so a trend is visible rather than a snapshot
  openInterest                    total open contracts — how much leverage is in the system
  globalLongShortAccountRatio     what share of accounts are positioned long

Funding rate is the useful one and the least understood. On a perpetual future there is no expiry
to force convergence with spot, so a periodic payment does it instead: when the perp trades above
spot, longs pay shorts, and vice versa. A persistently positive rate therefore means traders are
paying — every few hours — for the privilege of being long. That is a measure of crowding, and
crowded positioning is what makes a move violent when it reverses.

None of this is a forecast, and the interpretation layer that reads it says so.
"""
from __future__ import annotations

import logging
import time
from urllib.parse import urlparse

import httpx

log = logging.getLogger("tradeos.ingestion.derivatives")

HOST = "fapi.binance.com"
BASE = "https://fapi.binance.com"
UA = {"User-Agent": "Rhumb/1.0 (market-structure research; contact via the application)"}

# The perpetuals with enough depth for funding to mean anything. A thin market's funding rate is
# noise, and presenting it beside Bitcoin's would imply they carry the same weight.
TRACKED = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT")

MIN_INTERVAL_S = 0.35        # Binance's public weight limits are generous; this stays well inside
_last_call = 0.0


def _get(client: httpx.Client, path: str, params: dict) -> object:
    global _last_call
    wait = MIN_INTERVAL_S - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    url = BASE + path
    if urlparse(url).hostname != HOST:
        raise ValueError("binance host allowlist violation")
    resp = client.get(url, params=params)
    _last_call = time.monotonic()
    resp.raise_for_status()
    return resp.json()


def funding_trend(history: list[dict]) -> dict:
    """Where funding has been going, from the funding history. Pure.

    A single funding print is a snapshot; the shape is what says whether positioning is building
    or unwinding, which is the part that matters."""
    rates = [float(h["fundingRate"]) for h in history if "fundingRate" in h]
    if not rates:
        return {"current": None, "mean": None, "direction": "unknown", "periods": 0}
    recent = rates[-1]
    mean = sum(rates) / len(rates)
    older = rates[: max(1, len(rates) // 2)]
    older_mean = sum(older) / len(older)
    if abs(recent) < 0.00005:
        direction = "flat"
    elif recent > older_mean * 1.15:
        direction = "building"
    elif recent < older_mean * 0.85:
        direction = "unwinding"
    else:
        direction = "steady"
    return {"current": round(recent, 8), "mean": round(mean, 8),
            "direction": direction, "periods": len(rates)}


def annualised(rate: float | None, per_day: int = 3) -> float | None:
    """Funding as an annual percentage, which is the only form in which it is legible.

    0.01% per eight-hour period sounds like nothing; it is about 11% a year to hold the position.
    Showing the raw figure without this is how a real cost gets ignored."""
    return None if rate is None else round(rate * per_day * 365 * 100, 2)


# Five symbols x four endpoints x 0.35s pacing is roughly seven seconds of wall time — fine for a
# background job, unacceptable for a page load, and wasteful besides: funding settles every eight
# hours and open interest moves on the order of minutes. So the whole result is cached.
CACHE_TTL_S = 300
_cache: tuple[float, dict] | None = None


def fetch_cached(symbols: tuple[str, ...] = TRACKED) -> dict:
    """`fetch()` behind a short TTL. What every request path should call."""
    global _cache
    now = time.monotonic()
    if _cache and now - _cache[0] < CACHE_TTL_S:
        return {**_cache[1], "cached": True}
    fresh = fetch(symbols)
    if fresh.get("positioning"):          # never cache an empty result over a good one
        _cache = (now, fresh)
    return {**fresh, "cached": False}


def fetch(symbols: tuple[str, ...] = TRACKED) -> dict:
    """Positioning for each tracked perpetual. Never raises — a symbol that fails is omitted and
    reported, because a partial picture is still useful and a fabricated one never is."""
    out: dict[str, dict] = {}
    failed: list[str] = []
    with httpx.Client(timeout=25.0, headers=UA) as client:
        for sym in symbols:
            try:
                premium = _get(client, "/fapi/v1/premiumIndex", {"symbol": sym})
                history = _get(client, "/fapi/v1/fundingRate", {"symbol": sym, "limit": 12})
                oi = _get(client, "/fapi/v1/openInterest", {"symbol": sym})
                ratio = _get(client, "/futures/data/globalLongShortAccountRatio",
                             {"symbol": sym, "period": "1d", "limit": 2})
            except Exception as exc:
                log.warning("derivatives fetch failed for %s (%s)", sym, type(exc).__name__)
                failed.append(sym)
                continue
            trend = funding_trend(history if isinstance(history, list) else [])
            long_share = None
            if isinstance(ratio, list) and ratio:
                try:
                    long_share = round(float(ratio[-1]["longAccount"]), 4)
                except (KeyError, ValueError, TypeError):
                    long_share = None
            out[sym] = {
                "symbol": sym.replace("USDT", ""),
                "mark_price": float(premium.get("markPrice", 0)) or None,
                "funding_rate": trend["current"],
                "funding_annualised_pct": annualised(trend["current"]),
                "funding_direction": trend["direction"],
                "funding_periods": trend["periods"],
                "open_interest": float(oi.get("openInterest", 0)) or None,
                "long_account_share": long_share,
            }
    return {"positioning": out, "failed": failed,
            "source": "Binance public futures API (no key required)"}
