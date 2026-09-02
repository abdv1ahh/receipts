"""What the system itself was showing at the moment a call was published, frozen.

`journal_context.py` already does exactly this for a trade: it takes the Radar's own relevance
ranking at an instant, records how many interpretations were live, how many named the same
instrument, and whether they pointed the same way as the position. A call is the same shape of
object as a trade for this purpose, so this module is an ADAPTER and not a second implementation.
Two copies of "what was the world showing" would drift, and the copy that drifted would be the one
writing a permanent record.

Why freeze it at all. A caller who publishes a call the system was already pointing at is doing
something different from one who publishes against it, and neither is visible afterwards unless it
was recorded at the time. Reconstructed later, the answer would always flatter whoever
reconstructed it.
"""
from __future__ import annotations

from datetime import datetime

import psycopg

from .. import journal_context


def capture(conn: psycopg.Connection, user_id: int | None, symbol: str, direction: str,
            as_of: datetime) -> dict:
    """The frozen snapshot for one call. Returns a JSON-serialisable dict, never None.

    `user_id` may be None: an algorithm caller has no reader, and `relevance.reader_frame` already
    handles the signed-out frame, so the ranking degrades to un-personalised rather than failing.

    `alignment()` speaks the journal's vocabulary for direction (long / short), so the call's
    up / down is translated here rather than by widening that function. One caller's translation
    is cheaper than a second meaning for an argument.
    """
    with conn.cursor() as cur:
        ranked = journal_context.ranked_for(cur, user_id, as_of)
    trade_shaped = {"symbol": symbol, "direction": "short" if direction == "down" else "long"}
    ctx = journal_context.summarize(ranked, trade_shaped, as_of, basis="live")
    return _serialisable(ctx)


def empty(as_of: datetime, why: str) -> dict:
    """An honest empty snapshot.

    When the claim engine is producing nothing, the snapshot has to SAY that. An absent
    context_snapshot and a context_snapshot recording that the engine was silent look identical to
    a reader otherwise, and they are not the same fact: one means we did not look, the other means
    we looked and there was nothing. The second is a finding about the engine.
    """
    return {"as_of": as_of.isoformat(), "basis": "unavailable", "claim_ids": [], "n_live": 0,
            "n_on_symbol": 0, "alignment": "none", "mean_novelty": None, "unavailable_reason": why,
            "snapshot": {"claims": [], "on_symbol": [], "symbol": None, "direction": None}}


def _serialisable(ctx: dict) -> dict:
    """Datetimes to ISO strings, so the dict can go straight into a jsonb column."""
    out = dict(ctx)
    as_of = out.get("as_of")
    if isinstance(as_of, datetime):
        out["as_of"] = as_of.isoformat()
    return out
