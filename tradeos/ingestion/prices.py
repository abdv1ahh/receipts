"""End-of-day price ingestion via Tiingo (decision #27 — Stooq was bot-gated).

A dedicated, throttled, allowlisted client (we do not widen EdgarClient). We store the
split/dividend-ADJUSTED series (adjOpen/High/Low/Close/adjVolume) so forward returns are
correct, and record `source = 'tiingo:adjusted'` per row. Prices are labeled demo-grade on
the methodology page; a licensed EOD feed is the first post-funding purchase.
"""
from __future__ import annotations

import logging
import time
from datetime import UTC, date, datetime
from urllib.parse import urlparse

import httpx
import psycopg

from .common import reject

log = logging.getLogger("tradeos.ingest.prices")
SOURCE = "tiingo:adjusted"
TIINGO_HOST = "api.tiingo.com"


class TiingoClient:
    def __init__(self, api_key: str, min_interval: float = 0.12):
        if not api_key:
            raise ValueError("TIINGO_API_KEY is not set")
        self._key = api_key
        self._client = httpx.Client(headers={"Content-Type": "application/json"},
                                    timeout=30.0, follow_redirects=False)
        self._min_interval = min_interval
        self._last = 0.0

    def _throttle(self) -> None:
        wait = self._min_interval - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()

    def daily(self, ticker: str, start: date, end: date) -> list[dict] | None:
        """Return the daily price rows, or None if the ticker is unknown / has no data."""
        url = f"https://{TIINGO_HOST}/tiingo/daily/{ticker.lower()}/prices"
        if urlparse(url).hostname != TIINGO_HOST:
            raise ValueError("Tiingo host allowlist violation")
        self._throttle()
        resp = self._client.get(url, params={"startDate": start.isoformat(),
                                             "endDate": end.isoformat(), "token": self._key})
        if resp.status_code == 404:
            return None
        if resp.status_code == 429:
            log.warning("Tiingo 429; backing off 30s")
            time.sleep(30)
            resp = self._client.get(url, params={"startDate": start.isoformat(),
                                                 "endDate": end.isoformat(), "token": self._key})
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) and data else None

    def close(self) -> None:
        self._client.close()


def _valid_row(row: dict, today: date) -> tuple[date, float, float, float, float, float] | None:
    """Validate and return (day, open, high, low, close, volume) from the adjusted series,
    or None if the row is unusable."""
    try:
        day = datetime.fromisoformat(row["date"][:10]).date()
    except (KeyError, ValueError):
        return None
    if day > today:
        return None
    o, h, low, c = row.get("adjOpen"), row.get("adjHigh"), row.get("adjLow"), row.get("adjClose")
    v = row.get("adjVolume")
    if c is None or c <= 0:
        return None
    if h is not None and low is not None and h < low:
        return None
    return day, o, h, low, c, v


# Once the free tier's hourly ceiling is reached, every remaining symbol in the pass will 429 too —
# `TiingoClient.daily` has already spent its one 30s retry by the time it raises. Measured
# 2026-08-24: the ceiling is roughly 57 unique symbols in an hour, and a 400-symbol pass that
# ignores this does not fetch 400 symbols, it fetches ~50 and then spends the rest of the quota
# proving it is rate limited. Stopping the pass early is the difference between a top-up that
# finishes in nine hours and one that never finishes at all.
CONSECUTIVE_RATE_LIMITS = 3


def _is_rate_limit(exc: Exception) -> bool:
    return "429" in str(exc)


def ingest_prices(conn: psycopg.Connection, client: TiingoClient, symbols: list[str], start: date) -> dict:
    counters = {"symbols": len(symbols), "with_data": 0, "no_data": 0, "rows": 0, "rejected": 0,
                "rate_limited": False}
    today = datetime.now(UTC).date()
    consecutive = 0
    for symbol in symbols:
        try:
            rows = client.daily(symbol, start, today)
        except Exception as exc:  # one bad symbol must never kill the run
            reject(conn, "prices", symbol, f"{type(exc).__name__}: {exc}", counters)
            conn.commit()
            consecutive = consecutive + 1 if _is_rate_limit(exc) else 0
            if consecutive >= CONSECUTIVE_RATE_LIMITS:
                counters["rate_limited"] = True
                log.warning("prices: %d consecutive 429s; stopping this pass with %d symbols "
                            "untried", consecutive, len(symbols) - symbols.index(symbol) - 1)
                break
            continue
        consecutive = 0
        if not rows:
            counters["no_data"] += 1
            continue
        inserted = 0
        with conn.cursor() as cur:
            for row in rows:
                v = _valid_row(row, today)
                if v is None:
                    continue
                day, o, h, low, c, vol = v
                cur.execute(
                    """INSERT INTO prices_eod (symbol, day, open, high, low, close, volume, source)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (symbol, day) DO UPDATE SET
                           open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low,
                           close=EXCLUDED.close, volume=EXCLUDED.volume, source=EXCLUDED.source""",
                    (symbol.upper(), day, o, h, low, c, vol, SOURCE),
                )
                inserted += 1
        conn.commit()
        counters["with_data"] += 1
        counters["rows"] += inserted
        log.info("prices %s: %d rows", symbol, inserted)
    return counters
