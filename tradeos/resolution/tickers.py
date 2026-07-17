"""Ingest the SEC's own company_tickers.json into entities + security_map.

This is the confidence-1.0 backbone of resolution: every US-listed issuer the SEC knows,
mapped CIK <-> ticker <-> name, fetched through the throttled EdgarClient (the file lives
on www.sec.gov, already in the allowlist).
"""
from __future__ import annotations

import json
import logging

import psycopg

from ..ingestion.edgar_client import EdgarClient
from .entities import get_or_create_entity

log = logging.getLogger("tradeos.resolution")

COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"


def sync_tickers(conn: psycopg.Connection, client: EdgarClient) -> dict:
    """Idempotent: entities dedupe on CIK, security_map rows dedupe on the partial unique
    index (entity_id, symbol) where cusip is null. Re-running is a no-op."""
    raw = client.get(COMPANY_TICKERS_URL).content.decode("utf-8")
    data = json.loads(raw)
    counters = {"entities": 0, "mappings": 0}
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM entities")
        before = cur.fetchone()[0]
        for rec in data.values():
            cik = str(rec["cik_str"])            # already leading-zero-free
            symbol = (rec.get("ticker") or "").strip().upper()
            name = (rec.get("title") or "").strip()
            if not symbol or not name:
                continue
            eid = get_or_create_entity(cur, cik, name, "issuer")
            cur.execute(
                """INSERT INTO security_map (entity_id, symbol, source, confidence)
                   VALUES (%s, %s, 'sec_company_tickers', 1.0)
                   ON CONFLICT (entity_id, symbol) WHERE cusip IS NULL DO NOTHING""",
                (eid, symbol),
            )
            counters["mappings"] += cur.rowcount
        cur.execute("SELECT count(*) FROM entities")
        counters["entities"] = cur.fetchone()[0] - before
    conn.commit()
    log.info("sync-tickers: %d issuers total, +%d new entities, +%d new mappings",
             len(data), counters["entities"], counters["mappings"])
    return counters
