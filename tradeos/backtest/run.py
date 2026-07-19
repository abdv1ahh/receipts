"""Backtest DB drivers: derive episodes from the computed clusters, write forward-return
outcomes as horizons close, and summarize calibration per confidence bucket per horizon.
All the arithmetic lives in engine.py; this module only reads/writes the store.
"""
from __future__ import annotations

import logging
from collections import defaultdict

import psycopg

from .engine import (HORIZONS, Series, bucket_calibration, entry_day_after,
                     excess_return, group_episodes)

log = logging.getLogger("tradeos.backtest")
ALL_BUCKETS = ("low", "medium", "high")


def load_series(conn: psycopg.Connection, symbol: str) -> Series:
    with conn.cursor() as cur:
        cur.execute("SELECT day, close FROM prices_eod WHERE symbol = %s ORDER BY day", (symbol,))
        return Series.from_rows(cur.fetchall())


def symbols_for_clusters(conn: psycopg.Connection) -> list[str]:
    """Distinct exchange-listed symbols behind any computed cluster, plus SPY (benchmark)."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT DISTINCT m.symbol FROM signal_clusters c
               JOIN security_map m ON m.entity_id = c.issuer_entity AND m.source = 'sec_company_tickers'
               WHERE m.symbol IS NOT NULL"""
        )
        symbols = sorted({r[0] for r in cur.fetchall()})
    return symbols + ["SPY"]


def symbols_for_clusters_missing(conn: psycopg.Connection) -> list[str]:
    """Only the cluster symbols with NO prices yet — so a free-tier pull spends its limited
    quota on new symbols instead of re-fetching ones already stored."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT DISTINCT m.symbol FROM signal_clusters c
               JOIN security_map m ON m.entity_id = c.issuer_entity AND m.source = 'sec_company_tickers'
               WHERE m.symbol IS NOT NULL
                 AND NOT EXISTS (SELECT 1 FROM prices_eod p WHERE p.symbol = m.symbol)"""
        )
        missing = sorted({r[0] for r in cur.fetchall()})
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM prices_eod WHERE symbol = 'SPY' LIMIT 1")
        if not cur.fetchone():
            missing.append("SPY")
    return missing


def symbols_for_clusters_missing_history(conn: psycopg.Connection, before: date) -> list[str]:
    """Cluster symbols that have NO price row before `before` — i.e. still missing the deep
    history the liquidity floor needs for pre-`before` as_of dates. A symbol already priced only
    in the recent era counts as missing here, so a patient free-tier pass extends it back one batch
    at a time (each fetched symbol gains pre-`before` rows and drops out of the next pass)."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT DISTINCT m.symbol FROM signal_clusters c
               JOIN security_map m ON m.entity_id = c.issuer_entity AND m.source = 'sec_company_tickers'
               WHERE m.symbol IS NOT NULL
                 AND NOT EXISTS (SELECT 1 FROM prices_eod p WHERE p.symbol = m.symbol AND p.day < %s)""",
            (before,),
        )
        missing = sorted({r[0] for r in cur.fetchall()})
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM prices_eod WHERE symbol = 'SPY' AND day < %s LIMIT 1", (before,))
        if not cur.fetchone():
            missing.append("SPY")
    return missing


def _cluster_rows(conn: psycopg.Connection):
    with conn.cursor() as cur:
        cur.execute(
            """SELECT c.issuer_entity, c.id, c.as_of, c.confidence_bucket,
                      (SELECT symbol FROM security_map m WHERE m.entity_id = c.issuer_entity
                         AND m.source = 'sec_company_tickers' ORDER BY confidence DESC LIMIT 1)
               FROM signal_clusters c ORDER BY c.issuer_entity, c.as_of"""
        )
        return cur.fetchall()


def _by_issuer(rows):
    grouped = defaultdict(list)
    for issuer, cid, as_of, bucket, symbol in rows:
        grouped[issuer].append((as_of.date(), cid, bucket, symbol))
    return grouped


def run_backtest(conn: psycopg.Connection) -> dict:
    """Write signal_outcomes for each episode-entry cluster that can be entered. Excess columns
    stay NULL for horizons that have not closed; episodes without price history are skipped and
    counted (never silently)."""
    spy = load_series(conn, "SPY")
    if not spy.days:
        raise RuntimeError("no SPY prices found; run `ingest-prices` first (SPY is the benchmark)")

    grouped = _by_issuer(_cluster_rows(conn))
    counters = {"raw_clusters": sum(len(v) for v in grouped.values()), "episodes": 0,
                "priced_episodes": 0, "excluded_no_symbol": 0, "excluded_no_price_history": 0,
                "too_recent_to_enter": 0, "outcomes_written": 0}
    series_cache: dict[str, Series] = {}

    with conn.cursor() as cur:
        for items in grouped.values():
            symbol = items[0][3]
            for episode in group_episodes([(d, cid, b) for (d, cid, b, _s) in items]):
                counters["episodes"] += 1
                entry_as_of, entry_cid, _bucket = episode[0]
                if not symbol:
                    counters["excluded_no_symbol"] += 1
                    continue
                if symbol not in series_cache:
                    series_cache[symbol] = load_series(conn, symbol)
                sym = series_cache[symbol]
                if not sym.days:
                    counters["excluded_no_price_history"] += 1  # delisted / unknown to Tiingo
                    continue
                entry_day = entry_day_after(sym, entry_as_of)
                if entry_day is None:
                    counters["too_recent_to_enter"] += 1  # as_of newer than available prices; not startable yet
                    continue
                ex = {h: excess_return(sym, spy, entry_as_of, h)[0] for h in HORIZONS}
                cur.execute(
                    """INSERT INTO signal_outcomes (cluster_id, entry_day, excess_30, excess_90, excess_180)
                       VALUES (%s, %s, %s, %s, %s)
                       ON CONFLICT (cluster_id) DO UPDATE SET
                           entry_day = EXCLUDED.entry_day, excess_30 = EXCLUDED.excess_30,
                           excess_90 = EXCLUDED.excess_90, excess_180 = EXCLUDED.excess_180,
                           computed_at = now()""",
                    (entry_cid, entry_day, ex[30], ex[90], ex[180]),
                )
                counters["priced_episodes"] += 1
                counters["outcomes_written"] += 1
    conn.commit()
    log.info("run-backtest: %s", counters)
    return counters


def compute_calibration(conn: psycopg.Connection) -> dict:
    """Read-only calibration summary per bucket per horizon, with honest exclusion and
    open-horizon counts. This is what the methodology page and dashboard consume."""
    grouped = _by_issuer(_cluster_rows(conn))
    with conn.cursor() as cur:
        cur.execute("SELECT cluster_id, excess_30, excess_90, excess_180 FROM signal_outcomes")
        outcomes = {cid: {30: e30, 90: e90, 180: e180} for cid, e30, e90, e180 in cur.fetchall()}
        cur.execute("SELECT DISTINCT symbol FROM prices_eod")
        symbols_with_prices = {r[0] for r in cur.fetchall()}
        cur.execute("SELECT DISTINCT source FROM prices_eod LIMIT 5")
        price_sources = [r[0] for r in cur.fetchall()]
        cur.execute("SELECT min(entry_day) FROM signal_outcomes WHERE excess_30 IS NOT NULL OR excess_90 IS NOT NULL OR excess_180 IS NOT NULL")
        _min_entry = cur.fetchone()[0]
        sample_start_year = _min_entry.year if _min_entry else None

    values: dict[str, dict[int, list[float]]] = {b: {h: [] for h in HORIZONS} for b in ALL_BUCKETS}
    episodes_total = priced = excl_no_symbol = excl_no_history = too_recent = 0
    horizons_open = {h: 0 for h in HORIZONS}
    for items in grouped.values():
        symbol = items[0][3]
        for episode in group_episodes([(d, cid, b) for (d, cid, b, _s) in items]):
            episodes_total += 1
            _d, cid, bucket = episode[0]
            o = outcomes.get(cid)
            if o is None:
                if not symbol:
                    excl_no_symbol += 1                       # unresolved ticker
                elif symbol.upper() not in symbols_with_prices:
                    excl_no_history += 1                      # delisted / unknown to price feed
                else:
                    too_recent += 1                           # signal too recent to enter yet
                continue
            priced += 1
            for h in HORIZONS:
                if o[h] is None:
                    horizons_open[h] += 1
                elif bucket in values:
                    values[bucket][h].append(float(o[h]))

    per_bucket = {
        b: {str(h): {**bucket_calibration(values[b][h]), "sample_start_year": sample_start_year}
            for h in HORIZONS}
        for b in ALL_BUCKETS
    }
    return {
        "per_bucket": per_bucket,
        "sample_start_year": sample_start_year,
        "episodes_total": episodes_total,
        "episodes_priced": priced,
        "episodes_excluded_missing_prices": excl_no_history,
        "episodes_excluded_no_symbol": excl_no_symbol,
        "episodes_too_recent_to_enter": too_recent,
        "horizons_open": {str(h): horizons_open[h] for h in HORIZONS},
        "raw_cluster_count": sum(len(v) for v in grouped.values()),
        "horizons": list(HORIZONS),
        "conventions": {
            "entry": "close of the first trading day after the cluster's as_of",
            "exit": "close of the first trading day on/after entry + horizon calendar days",
            "metric": "excess return vs SPY; a hit is excess > 0",
            "episode": "issuer clusters within 14 days are one episode, entered once at the first day",
            "min_episodes_for_display": 30,
        },
        "price_grade": (f"demo-grade EOD prices ({', '.join(price_sources)}); a licensed feed is the "
                        "first post-funding purchase" if price_sources else "no prices ingested yet"),
        "live_commitment": ("Live track record accrues from launch; the live calibration curve "
                            "replaces this backtest at 200 resolved signals per type."),
    }
