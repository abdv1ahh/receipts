"""Pro-tier API keys (Slice D): scoped, rotatable, stored hashed — plus a per-key canary trace so
a resold dataset is traceable to the key that leaked it.

The raw key is shown to the user exactly once and never stored; we keep only its sha256. The canary
is a per-key seed; every v1 response carries `meta.trace = sha256(canary:day)`, which is response
metadata (not fabricated signal data), so a leaked dump identifies the leaking key without ever
polluting the data itself.
"""
from __future__ import annotations

import hashlib
import secrets
import time

import psycopg

KEY_PREFIX = "tos_live_"


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def canary_trace(canary: str, day: str) -> str:
    """Deterministic per-key, per-day trace token embedded in v1 response metadata."""
    return hashlib.sha256(f"{canary}:{day}".encode()).hexdigest()[:16]


def generate(conn: psycopg.Connection, user_id: int, name: str | None, scopes=("read",)) -> dict:
    raw = KEY_PREFIX + secrets.token_urlsafe(24)
    canary = secrets.token_hex(8)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO api_keys (user_id, name, prefix, key_hash, scopes, canary) "
            "VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
            (user_id, (name or "").strip()[:60] or "key", raw[:12], _hash(raw), list(scopes), canary),
        )
        kid = cur.fetchone()[0]
    conn.commit()
    return {"id": kid, "key": raw, "prefix": raw[:12]}   # raw returned once, never persisted


def verify(conn: psycopg.Connection, raw: str | None) -> dict | None:
    if not raw:
        return None
    with conn.cursor() as cur:
        cur.execute(
            "SELECT k.id, k.user_id, k.scopes, k.canary, u.tier FROM api_keys k JOIN users u ON u.id=k.user_id "
            "WHERE k.key_hash=%s AND k.revoked_at IS NULL",
            (_hash(raw),),
        )
        r = cur.fetchone()
        if not r:
            return None
        cur.execute("UPDATE api_keys SET last_used_at=now() WHERE id=%s", (r[0],))
        conn.commit()
    return {"id": r[0], "user_id": r[1], "scopes": r[2], "canary": r[3], "tier": r[4]}


def list_keys(conn: psycopg.Connection, user_id: int) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, name, prefix, scopes, created_at, last_used_at, revoked_at "
            "FROM api_keys WHERE user_id=%s ORDER BY created_at DESC",
            (user_id,),
        )
        return [{"id": i, "name": n, "prefix": p, "scopes": s, "created_at": c.isoformat(),
                 "last_used_at": lu.isoformat() if lu else None, "revoked": rv is not None}
                for i, n, p, s, c, lu, rv in cur.fetchall()]


def revoke(conn: psycopg.Connection, user_id: int, key_id: int) -> bool:
    with conn.cursor() as cur:
        cur.execute("UPDATE api_keys SET revoked_at=now() WHERE id=%s AND user_id=%s AND revoked_at IS NULL",
                    (key_id, user_id))
        conn.commit()
        return cur.rowcount > 0


# Per-key sliding-window rate limit (in-memory demo; a shared limiter replaces it at the edge).
_hits: dict[int, list[float]] = {}


def rate_ok(key_id: int, limit: int = 60, window: int = 60) -> bool:
    now = time.time()
    q = _hits.setdefault(key_id, [])
    q[:] = [t for t in q if now - t < window]
    if len(q) >= limit:
        return False
    q.append(now)
    return True
