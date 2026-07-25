"""FINRA consolidated short-interest ingestion (Slice 5), a context source.

Dedicated allowlisted client (we do not widen EdgarClient). We fetch the derived fields we
display — current/previous short position, the change, days-to-cover — map each row to an
issuer strictly by symbol (never guessed), and store two timestamps: settlement_date (event)
and a publication knowable_time (~8 business days later). Not yet weighted into the score
(decision #31).
"""
from __future__ import annotations

import logging
import time
from datetime import UTC, date, datetime, timedelta
from urllib.parse import urlparse

import httpx
import psycopg

log = logging.getLogger("tradeos.ingest.finra")
SOURCE = "finra:consolidated"
FINRA_HOST = "api.finra.org"
FINRA_URL = "https://api.finra.org/data/group/otcMarket/name/consolidatedShortInterest"
PUBLICATION_LAG_BDAYS = 8  # FINRA disseminates ~8 business days after settlement (documented approx)


def _add_business_days(d: date, n: int) -> date:
    while n > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


class FinraClient:
    def __init__(self, min_interval: float = 0.3):
        self._client = httpx.Client(
            headers={"Content-Type": "application/json", "Accept": "application/json",
                     "User-Agent": "TradeOSS contact@example.com"},
            timeout=60.0, follow_redirects=False)
        self._min_interval = min_interval
        self._last = 0.0

    def _throttle(self) -> None:
        wait = self._min_interval - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()

    def since(self, start: date, page: int = 5000):
        """Yield short-interest rows with settlementDate >= start, paginated."""
        if urlparse(FINRA_URL).hostname != FINRA_HOST:
            raise ValueError("FINRA host allowlist violation")
        offset = 0
        while True:
            self._throttle()
            body = {
                "limit": page, "offset": offset,
                "dateRangeFilters": [{"fieldName": "settlementDate",
                                      "startDate": start.isoformat(), "endDate": "2099-12-31"}],
            }
            resp = self._client.post(FINRA_URL, json=body)
            resp.raise_for_status()
            rows = resp.json()
            if not rows:
                return
            yield from rows
            if len(rows) < page:
                return
            offset += page

    def close(self) -> None:
        self._client.close()


def _entity_map(conn: psycopg.Connection) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute("SELECT symbol, entity_id FROM security_map WHERE source = 'sec_company_tickers'")
        return dict(cur.fetchall())


def ingest_short_interest(conn: psycopg.Connection, client: FinraClient, start: date) -> dict:
    """Ingest short interest for symbols known to security_map since `start`. Idempotent on
    (symbol, settlement_date)."""
    symbols = _entity_map(conn)
    counters = {"fetched": 0, "stored": 0, "skipped_unmapped": 0}
    with conn.cursor() as cur:
        for row in client.since(start):
            counters["fetched"] += 1
            symbol = (row.get("symbolCode") or "").strip().upper()
            entity = symbols.get(symbol)
            if entity is None:
                counters["skipped_unmapped"] += 1
                continue
            try:
                settlement = datetime.fromisoformat(row["settlementDate"][:10]).date()
            except (KeyError, TypeError, ValueError):
                continue
            knowable = datetime.combine(_add_business_days(settlement, PUBLICATION_LAG_BDAYS),
                                        datetime.min.time(), tzinfo=UTC).replace(hour=21)
            cur_short = row.get("currentShortPositionQuantity")
            prev_short = row.get("previousShortPositionQuantity")
            change = row.get("changePreviousNumber")
            if change is None and cur_short is not None and prev_short is not None:
                change = cur_short - prev_short
            cur.execute(
                """INSERT INTO short_interest
                   (symbol, issuer_entity, settlement_date, knowable_time, current_short,
                    previous_short, change_short, avg_daily_volume, days_to_cover, source)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (symbol, settlement_date) DO UPDATE SET
                       issuer_entity=EXCLUDED.issuer_entity, knowable_time=EXCLUDED.knowable_time,
                       current_short=EXCLUDED.current_short, previous_short=EXCLUDED.previous_short,
                       change_short=EXCLUDED.change_short, avg_daily_volume=EXCLUDED.avg_daily_volume,
                       days_to_cover=EXCLUDED.days_to_cover""",
                (symbol, entity, settlement, knowable, cur_short, prev_short, change,
                 row.get("averageDailyVolumeQuantity"), row.get("daysToCoverQuantity"), SOURCE),
            )
            counters["stored"] += 1
    conn.commit()
    log.info("ingest-short-interest: %s", counters)
    return counters
