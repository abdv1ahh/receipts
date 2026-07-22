"""Feature flags (Slice K): a real, DB-backed, request-path-enforced control surface.

This is deliberately NOT theatre. Every flag here gates behaviour the server actually checks on a
live request — flipping a row in the admin console changes what the API does. The flags are chosen to
be safe to toggle at runtime and genuinely useful to a bootstrapped operator:

  ai_assistant      off -> the assistant answers from the deterministic grounded template only,
                          never calling the LLM (a real cost / quota kill-switch).
  ai_trade_analysis off -> trade analysis uses the deterministic template, never the LLM (ditto).
  registration      off -> new signups are refused ("registration temporarily closed").
  community_writes  off -> the community goes read-only (no comments / reactions / follows / reports).
  crypto            off -> the crypto market surface is hidden.

Things that are controlled by the deployment environment or a third-party key — the modular SEC
inputs (ENABLE_CONGRESS / ENABLE_SHORT_INTEREST), the sentiment source keys (Reddit / YouTube), and
Stripe — are NOT runtime flags. A web toggle can't conjure an API key, so the console shows their real
state read-only (config.py) rather than pretending a switch controls them. Same honesty rule as the
'not connected yet' sources elsewhere.

Rows live in the feature_flags table (migration 009). A short process-local TTL cache keeps this off
the hot path without letting a toggle go stale for more than a few seconds.
"""
from __future__ import annotations

import time

import psycopg

# name -> {label, description, default}. Only these names are surfaced/managed by the admin console;
# the dead seed rows in feature_flags (congress/short_interest/signals/previews) are ignored here.
FLAGS: dict[str, dict] = {
    "ai_assistant": {
        "label": "AI Market Assistant",
        "description": "Use the LLM to phrase assistant answers. Off falls back to the deterministic, "
                       "grounded answer with no model calls — a cost/quota kill-switch.",
        "default": True,
    },
    "ai_trade_analysis": {
        "label": "AI trade analysis",
        "description": "Use the LLM to phrase trade-journal analysis. Off uses the deterministic "
                       "template with no model calls.",
        "default": True,
    },
    "registration": {
        "label": "New registrations",
        "description": "Allow new accounts to sign up. Off closes registration for everyone.",
        "default": True,
    },
    "community_writes": {
        "label": "Community posting",
        "description": "Allow comments, reactions, follows and reports. Off makes the community "
                       "read-only (existing content stays visible).",
        "default": True,
    },
    "crypto": {
        "label": "Crypto surface",
        "description": "Show the crypto market-data surface. Off returns it as disabled.",
        "default": True,
    },
}

_TTL = 3.0                       # seconds; bounds how long a toggle can be stale
_cache: dict[str, tuple[bool, float]] = {}


def resolve_states(db_rows: dict[str, bool]) -> list[dict]:
    """Pure: merge the known flags' defaults with any DB overrides into console rows. Unknown DB
    rows are ignored; unset flags fall back to their default. Order is stable (FLAGS order)."""
    return [{"name": name, "label": meta["label"], "description": meta["description"],
             "enabled": bool(db_rows.get(name, meta["default"]))}
            for name, meta in FLAGS.items()]


def _default(name: str) -> bool:
    return bool(FLAGS.get(name, {}).get("default", True))


def enabled(conn: psycopg.Connection, name: str) -> bool:
    """True if the flag is on. Reads feature_flags, falling back to the compiled default, behind a
    short TTL cache so this is cheap to call on every request."""
    now = time.monotonic()
    hit = _cache.get(name)
    if hit and now - hit[1] < _TTL:
        return hit[0]
    with conn.cursor() as cur:
        cur.execute("SELECT enabled FROM feature_flags WHERE name=%s", (name,))
        r = cur.fetchone()
    val = bool(r[0]) if r else _default(name)
    _cache[name] = (val, now)
    return val


def effective_provider(conn: psycopg.Connection, flag_name: str) -> str | None:
    """For the AI kill-switches: return 'template' to force the deterministic path when the flag is
    off, or None to let the caller use its normal EXPLAIN_PROVIDER env default when it's on."""
    return None if enabled(conn, flag_name) else "template"


def set_flag(conn: psycopg.Connection, name: str, on: bool) -> dict:
    """Flip a known flag. Rejects unknown names so the console can't create phantom flags."""
    if name not in FLAGS:
        return {"error": "unknown flag"}
    with conn.cursor() as cur:
        cur.execute("INSERT INTO feature_flags (name, enabled) VALUES (%s,%s) "
                    "ON CONFLICT (name) DO UPDATE SET enabled=EXCLUDED.enabled", (name, on))
    conn.commit()
    _cache.pop(name, None)                    # make the toggle feel instant
    return {"name": name, "enabled": bool(on)}


def all_states(conn: psycopg.Connection) -> list[dict]:
    """Console view: every known flag with its current effective value."""
    with conn.cursor() as cur:
        cur.execute("SELECT name, enabled FROM feature_flags WHERE name = ANY(%s)", (list(FLAGS),))
        rows = {n: e for n, e in cur.fetchall()}
    return resolve_states(rows)
