"""What the system itself was showing at the moment a call was published, frozen.

RETIRED 2026-09-23, and retired rather than deleted, because `context_snapshot` is a SEALED column
(migration 035) and 474 rows already hold one. The module has to keep answering what those rows
mean even though nothing new is captured.

WHAT IT USED TO DO. `journal_context.ranked_for` gave the interpretation engine's own relevance
ranking at an instant, and `summarize` recorded how many interpretations were live, how many named
the same instrument, and whether they pointed the same way as the call. A caller who publishes a
call the system was already pointing at is doing something different from one who publishes against
it, and neither is visible afterwards unless it was recorded at the time.

WHY IT IS RETIRED. The interpretation engine it read is gone: the event spine, the claim engine and
the relevance ranking are not part of Receipts and were removed with everything else that is not.
The ONE thing that could not be done is keep calling `ranked_for` against a deleted engine, because
it would return `[]` and this module would faithfully record `n_live: 0, basis: "live"` — which
asserts *"we looked and there was nothing"* when the truth is *"there is no engine"*. Those are not
the same fact and one of them is a finding about the engine. `empty()` exists precisely to tell
them apart, so new calls now get `empty()` with the reason, and old snapshots keep meaning exactly
what they meant when they were sealed.

That is also why `capture` still exists with its old signature instead of being deleted along with
its caller: a sealed column whose producer vanished from the codebase leaves the next reader of
those 474 rows with no way to find out what they say.
"""
from __future__ import annotations

from datetime import datetime

import psycopg

# The date the interpretation engine was removed. In the sentence every call published from now on
# carries, so a reader of a 2027 snapshot can see why it is empty without reading this file.
RETIRED_ON = "2026-09-23"

RETIRED_REASON = (f"the interpretation engine this recorded was retired on {RETIRED_ON}, so there "
                  f"was nothing to look at rather than nothing found")


def capture(conn: psycopg.Connection, user_id: int | None, symbol: str, direction: str,
            as_of: datetime) -> dict:
    """The frozen snapshot for one call. Now always the honest empty one.

    Signature unchanged on purpose. The caller in `calls.publish` reads as it always did, and the
    difference between "we looked and the engine was silent" and "there is no engine" is carried in
    the snapshot itself where a reader of the sealed row can see it, rather than in the shape of a
    function call nobody will ever read again.
    """
    del conn, user_id, symbol, direction              # the engine they addressed is gone
    return empty(as_of, RETIRED_REASON)


def empty(as_of: datetime, why: str) -> dict:
    """An honest empty snapshot.

    An absent `context_snapshot` and one recording that nothing was live look identical to a reader
    otherwise, and they are not the same fact: one means we did not look, the other means we looked
    and there was nothing. `why` is what separates them, and it is why this function took a reason
    from the day it was written.
    """
    return {"as_of": as_of.isoformat(), "basis": "unavailable", "claim_ids": [], "n_live": 0,
            "n_on_symbol": 0, "alignment": "none", "mean_novelty": None, "unavailable_reason": why,
            "snapshot": {"claims": [], "on_symbol": [], "symbol": None, "direction": None}}
