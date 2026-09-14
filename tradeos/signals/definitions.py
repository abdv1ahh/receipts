"""Signal definition registry + the hash-guarded compute driver.

The guarantee (decision #24): compute refuses unless the computing module's current hash
matches the latest registered definition. Changing a constant or a line of logic changes
the hash, so a new version must be registered — with a changelog — before any cluster can
be recomputed. Meaning cannot drift silently.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import psycopg
from psycopg.types.json import Json

from . import convergence

log = logging.getLogger("tradeos.signals")


class DefinitionMismatch(RuntimeError):
    pass


def latest_definition(conn: psycopg.Connection, name: str) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT id, version, params, code_hash, changelog, created_at
               FROM signal_definitions WHERE name = %s ORDER BY version DESC LIMIT 1""",
            (name,),
        )
        r = cur.fetchone()
    if not r:
        return None
    return {"id": r[0], "version": r[1], "params": r[2], "code_hash": r[3], "changelog": r[4], "created_at": r[5]}


def register(conn: psycopg.Connection, changelog: str, module=convergence) -> tuple[int, bool]:
    """Register a signal module as a definition version. No-op if the module hash already
    matches the latest registered version. Returns (version, created?).

    `module` is a parameter rather than a hardcoded import because there is now more than one
    signal: `signals.insider` is a pure Form 4 definition registered under its own NAME, so
    that its versions number independently of `convergence`'s and a new definition here cannot
    move `max(version)` under `convergence`. Any module with NAME, DEFAULT_PARAMS and
    module_code_hash() fits.
    """
    name = module.NAME
    code_hash = module.module_code_hash()
    latest = latest_definition(conn, name)
    if latest and latest["code_hash"] == code_hash:
        return latest["version"], False
    version = (latest["version"] + 1) if latest else 1
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO signal_definitions (name, version, params, code_hash, changelog)
               VALUES (%s, %s, %s, %s, %s)""",
            (name, version, Json(module.DEFAULT_PARAMS), code_hash, changelog),
        )
    conn.commit()
    log.info("registered %s v%d (hash %s)", name, version, code_hash[:12])
    return version, True


def check_definition(latest: dict | None, name: str, current_hash: str) -> dict:
    """Pure guard (offline-testable): the registered hash must match the running module."""
    if latest is None:
        raise DefinitionMismatch(
            f"no registered definition for '{name}'. Run: "
            f"python -m tradeos.cli signals-register --changelog 'initial {name} v1'"
        )
    if latest["code_hash"] != current_hash:
        raise DefinitionMismatch(
            f"'{name}' module changed since v{latest['version']} (code hash mismatch). "
            f"Signals may not silently change meaning. Register a new version first: "
            f"python -m tradeos.cli signals-register --changelog '<what changed and why>'"
        )
    return latest


def require_definition(conn: psycopg.Connection, name: str, current_hash: str) -> dict:
    return check_definition(latest_definition(conn, name), name, current_hash)


def _store_cluster(conn, defn, issuer, as_of, result, floor_ok, params) -> str:
    bucket = convergence.bucket_for(result.score, floor_ok, params)
    inputs = {
        "definition_version": defn["version"],
        "window_days": params["window_days"],
        "liquidity_floor": {"ok": floor_ok, "basis": "exchange_listing"},
        "contributions": result.contributions,
        "context": result.context,
        "freshest_knowable": result.freshest_knowable.isoformat() if result.freshest_knowable else None,
        "stalest_knowable": result.stalest_knowable.isoformat() if result.stalest_knowable else None,
    }
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO signal_clusters
               (definition_id, issuer_entity, as_of, score, confidence_bucket, voices, source_classes, inputs)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (definition_id, issuer_entity, as_of) DO UPDATE SET
                   score = EXCLUDED.score, confidence_bucket = EXCLUDED.confidence_bucket,
                   voices = EXCLUDED.voices, source_classes = EXCLUDED.source_classes, inputs = EXCLUDED.inputs""",
            (defn["id"], issuer, as_of, result.score, bucket, result.voices, result.source_classes, Json(inputs)),
        )
    return bucket


def compute_and_store(conn: psycopg.Connection, as_of: datetime) -> dict:
    """Compute clusters for a single as_of. Only gate-passing issuers are stored."""
    defn = require_definition(conn, convergence.NAME, convergence.module_code_hash())
    params = defn["params"]
    counters = {"as_of": as_of.isoformat(), "candidates": 0, "published": 0,
                "below_floor": 0, "low": 0, "medium": 0, "high": 0}
    issuers = convergence.candidate_issuers(conn, as_of, params)
    counters["candidates"] = len(issuers)
    for issuer in issuers:
        result = convergence.compute_for_issuer(conn, issuer, as_of, params)
        if not result.passes_gate:
            continue
        if not convergence.passes_liquidity_floor(conn, issuer, as_of, params):
            counters["below_floor"] += 1  # sub-floor clusters do not publish at all (decision #38)
            continue
        bucket = _store_cluster(conn, defn, issuer, as_of, result, True, params)
        counters["published"] += 1
        counters[bucket] += 1
    conn.commit()
    return counters


def compute_daily(conn: psycopg.Connection, from_date, to_date) -> list[dict]:
    """Compute a cluster set for each business day's end-of-day as_of. Slice 4's backtest
    replays these daily points; each represents exactly what was knowable that day."""
    out = []
    day = from_date
    while day <= to_date:
        if day.weekday() < 5:
            as_of = datetime(day.year, day.month, day.day, 23, 59, 59, tzinfo=UTC)
            out.append(compute_and_store(conn, as_of))
        day += timedelta(days=1)
    return out
