"""CUSIP -> issuer resolution via OpenFIGI's free mapping API (decision log #20).

13F identifies securities by CUSIP only, and company_tickers.json carries no CUSIP, so a
mapping utility is required. OpenFIGI is an identifier registry, not a signal aggregator,
so it does not compromise the clean data supply chain. This is a separate, small client —
we do not widen EdgarClient's allowlist.

Never guess: a CUSIP OpenFIGI cannot map, or that maps to a ticker we do not already know
from the SEC, stays unresolved. Its holding is excluded from convergence and shown flagged.
"""
from __future__ import annotations

import logging
import time
from urllib.parse import urlparse

import httpx
import psycopg

log = logging.getLogger("tradeos.resolution")

OPENFIGI_HOST = "api.openfigi.com"
OPENFIGI_URL = "https://api.openfigi.com/v3/mapping"
# unauthenticated free tier: ~25 requests/min, up to 10 jobs/request. Stay under it.
UNAUTH_MIN_INTERVAL = 2.5
UNAUTH_BATCH = 10


class OpenFigiClient:
    def __init__(self, api_key: str | None = None, min_interval: float = UNAUTH_MIN_INTERVAL):
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["X-OPENFIGI-APIKEY"] = api_key
        self._client = httpx.Client(headers=headers, timeout=30.0, follow_redirects=False)
        self._min_interval = min_interval
        self._batch = 100 if api_key else UNAUTH_BATCH
        self._last = 0.0

    def _throttle(self) -> None:
        wait = self._min_interval - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()

    @staticmethod
    def _pick_ticker(data: list[dict]) -> str | None:
        """Prefer a US-listed equity ticker; fall back to the first entry's ticker."""
        for row in data:
            if row.get("exchCode") == "US" and row.get("ticker"):
                return row["ticker"].strip().upper()
        for row in data:
            if row.get("ticker"):
                return row["ticker"].strip().upper()
        return None

    def map_cusips(self, cusips: list[str]) -> dict[str, str | None]:
        """Return {cusip: ticker or None}. Best-effort: transient errors on a batch leave
        those CUSIPs unresolved rather than aborting the whole run."""
        if urlparse(OPENFIGI_URL).hostname != OPENFIGI_HOST:
            raise ValueError("OpenFIGI host allowlist violation")
        out: dict[str, str | None] = {}
        for i in range(0, len(cusips), self._batch):
            batch = cusips[i:i + self._batch]
            self._throttle()
            body = [{"idType": "ID_CUSIP", "idValue": c} for c in batch]
            try:
                resp = self._client.post(OPENFIGI_URL, json=body)
                if resp.status_code == 429:
                    log.warning("OpenFIGI 429; backing off 60s")
                    time.sleep(60)
                    resp = self._client.post(OPENFIGI_URL, json=body)
                resp.raise_for_status()
                for cusip, item in zip(batch, resp.json()):
                    data = item.get("data") if isinstance(item, dict) else None
                    out[cusip] = self._pick_ticker(data) if data else None
            except (httpx.HTTPError, ValueError) as exc:
                log.warning("OpenFIGI batch failed (%s); leaving %d CUSIPs unresolved",
                            type(exc).__name__, len(batch))
                for cusip in batch:
                    out.setdefault(cusip, None)
        return out

    def close(self) -> None:
        self._client.close()


def resolve_cusips(conn: psycopg.Connection, figi: OpenFigiClient, limit: int) -> dict:
    """Resolve up to `limit` distinct unmapped CUSIPs from fund_holdings, store the
    mappings in security_map (confidence 0.9), then link holdings to entities. Unresolved
    CUSIPs stay unresolved."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT DISTINCT h.cusip FROM fund_holdings h
               WHERE h.issuer_entity IS NULL
                 AND NOT EXISTS (SELECT 1 FROM security_map m WHERE m.cusip = h.cusip)
               LIMIT %s""",
            (limit,),
        )
        cusips = [r[0] for r in cur.fetchall()]

    counters = {"queried": len(cusips), "mapped": 0, "linked": 0}
    if not cusips:
        return counters

    mapping = figi.map_cusips(cusips)
    with conn.cursor() as cur:
        for cusip, ticker in mapping.items():
            if not ticker:
                continue
            cur.execute(
                "SELECT entity_id FROM security_map WHERE symbol = %s AND source = 'sec_company_tickers' LIMIT 1",
                (ticker,),
            )
            row = cur.fetchone()
            if not row:
                continue  # ticker unknown to the SEC file: do not guess an entity
            cur.execute(
                """INSERT INTO security_map (entity_id, symbol, cusip, source, confidence)
                   VALUES (%s, %s, %s, 'openfigi', 0.9)
                   ON CONFLICT (entity_id, symbol, cusip) DO NOTHING""",
                (row[0], ticker, cusip),
            )
            counters["mapped"] += 1
        cur.execute(
            """UPDATE fund_holdings h SET issuer_entity = m.entity_id
               FROM security_map m
               WHERE m.cusip = h.cusip AND m.entity_id IS NOT NULL AND h.issuer_entity IS NULL"""
        )
        counters["linked"] = cur.rowcount
    conn.commit()
    log.info("resolve-cusips: queried %d, mapped %d, linked %d holdings",
             counters["queried"], counters["mapped"], counters["linked"])
    return counters
