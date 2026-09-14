"""The pure-insider signal: Form 4 open-market purchases, nothing else.

WHY IT IS A SEPARATE SIGNAL AND NOT `convergence` v5.

`convergence`'s publish gate is `min_source_classes: 2`, so every one of its 17,669 clusters
blends Form 4 activity with 13F holdings (quarterly, 45-day lag) or 13D/G stakes. A
pure-insider cluster is unreachable there by construction — `docs/analysis/signal_edge.md`
records cut (a) as structurally empty, n=0. The literature the product rests on (Cohen,
Malloy & Pomorski 2012; Lakonishok & Lee 2001; Jeng, Metrick & Zeckhauser 2003) is about
pure Form 4 purchases, so it has never actually been tested in this codebase. This is that
test.

It carries its own NAME rather than being registered as `convergence` v5 for two reasons,
both measured rather than stylistic:

  1. **`smartmoney_claims._definition_version()` reads `SELECT max(version) FROM
     signal_definitions` with no name filter**, and the scheduler calls it every cycle. A
     row with version 5 would restamp new claims `convergence-v5` when v3 logic produced
     them — and those claims are what the Receipts house records import from, into a table
     whose rows are sealed forever. A new name starts at version 1 and leaves `max(version)`
     at 4. (The underlying bug is fixed separately; this module does not depend on that fix.)

  2. **`convergence.py` is left byte-identical**, so its `module_code_hash()` still matches
     the registered v4 row and v3/v4 remain recomputable from this commit. Editing it to add
     params would have made the two versions this analysis is compared against
     unreproducible — which is the opposite of what a comparison needs.

WHAT IS REUSED, AND WHY THAT MATTERS. The scoring is `convergence.score_cluster`, unchanged
and imported, not copied. Its gate is already fully params-driven (`p["gate"]`), so
`min_source_classes: 1` and `min_voices: 2` need no new code — and because it is the same
function, a v5 score and a v3 score mean the same thing. A second scorer would drift, and
the drift would be silent (CLAUDE.md §0b2).

HOW THE ROUTINE EXCLUSION IS IMPLEMENTED. `gather_events` classifies each insider with
`opportunistic.classify_insider` and **does not emit an Event at all** for a routine one, so
a routine insider is neither a voice nor a contribution to the score. That is stronger than
"does not count toward min_voices" and it is the faithful reading of CMP: routine trades
predict nothing, so letting them add score while not adding a voice would smuggle the
discarded half back in through the other door. The count of exclusions is returned alongside
the events so nothing disappears silently.

POINT-IN-TIME DISCIPLINE is unchanged: every input is filtered on `knowable_time <= as_of`,
including the trade history used for classification, so a replay cannot see a filing that had
not been published on the day it is scoring.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from pathlib import Path

import psycopg

from . import convergence, opportunistic

NAME = "convergence_insider"

# Only the keys the pure-insider path can actually reach. The stake and holding weights are
# absent rather than set to zero: `gather_events` never emits those subtypes, so carrying them
# would describe behaviour this signal does not have.
DEFAULT_PARAMS = {
    "window_days": 90,
    "base_weights": {
        "insider_purchase": 1.0,       # code P, acquired. The only scored event.
    },
    "magnitude": {
        "insider_divisor": 6.0, "insider_cap": 1.5,    # log10(1+value)/6, as convergence
    },
    "half_life_days": {"insider": 14.0},
    "independence": {"secondary_weight": 0.25},
    # THE POINT OF THE EXERCISE. One source class, because there is only one source class.
    # min_voices drops 3 -> 2 because voices are no longer being recruited from three
    # different kinds of filing to reach the threshold; two insiders buying inside 90 days is
    # the Lakonishok & Lee "multiple insiders" condition at its lowest meaningful setting.
    "gate": {"min_source_classes": 1, "min_voices": 2},
    # Unchanged from convergence v3 (decision #38). The illiquid names were the performance
    # drag there and there is no reason to believe they are not here.
    "liquidity_floor_usd": 2000000.0,
    "liquidity_window_days": 90,
    "buckets": {"low_max": 3.0, "medium_max": 6.0},
    # Recorded in the definition row so the registered params state the rule, not just the
    # code. CMP 2012; see opportunistic.py for the full citation and deviations.
    "insider_classification": {
        "rule": "cohen_malloy_pomorski_2012",
        "lookback_years": opportunistic.LOOKBACK_YEARS,
        "excluded_from_gate": [opportunistic.ROUTINE],
        "counted": [opportunistic.OPPORTUNISTIC, opportunistic.UNCLASSIFIED],
    },
    "transaction_codes": ["P"],        # open-market purchase only: no S, no M, no A, no F
}

# Every file whose contents can change what this signal means. Hashing only this module would
# let a change to the scorer or the classifier pass the version guard unnoticed, which is the
# exact failure `module_code_hash` exists to prevent (decision #24).
_HASHED_SOURCES = ("insider.py", "opportunistic.py", "convergence.py")


def module_code_hash() -> str:
    """sha256 over this module, the classifier, and the scorer it delegates to.

    Three files rather than one because this signal's behaviour is spread across three. A
    guard that watched only the thin wrapper would happily recompute after someone edited the
    scoring function underneath it.
    """
    h = hashlib.sha256()
    here = Path(__file__).parent
    for name in _HASHED_SOURCES:
        h.update(name.encode())
        h.update((here / name).read_bytes())
    return h.hexdigest()


# ------------------------------------------------------------------ DB gather

def candidate_issuers(conn: psycopg.Connection, as_of: datetime, params: dict) -> list[int]:
    """Issuers with at least one knowable open-market purchase inside the window.

    Far narrower than `convergence.candidate_issuers`, which unions three tables: only Form 4
    code-P rows can start a cluster here, so there is nothing to gain from considering an
    issuer whose only activity in the window was a sale or a 13F.
    """
    window_start = as_of - timedelta(days=params["window_days"])
    with conn.cursor() as cur:
        cur.execute(
            """SELECT DISTINCT issuer_entity FROM insider_transactions
               WHERE issuer_entity IS NOT NULL
                 AND transaction_code = 'P' AND acquired_disposed = 'A'
                 AND knowable_time <= %s AND knowable_time > %s""",
            (as_of, window_start),
        )
        return [r[0] for r in cur.fetchall()]


def gather_events(conn: psycopg.Connection, issuer_entity: int, as_of: datetime,
                  params: dict) -> tuple[list[convergence.Event], dict]:
    """Open-market purchases in the window, routine insiders dropped.

    Returns (events, classification_counts). The counts are returned rather than logged
    because the analysis has to report how many insiders each label caught — on this dataset
    the answer is the finding, not a footnote.
    """
    window_start = as_of - timedelta(days=params["window_days"])
    events: list[convergence.Event] = []
    counts = {opportunistic.ROUTINE: 0, opportunistic.OPPORTUNISTIC: 0,
              opportunistic.UNCLASSIFIED: 0}

    with conn.cursor() as cur:
        cur.execute(
            """SELECT id, owner_cik, issuer_cik, shares, price_per_share, knowable_time, event_time
               FROM insider_transactions
               WHERE issuer_entity = %s AND transaction_code = 'P' AND acquired_disposed = 'A'
                 AND knowable_time <= %s AND knowable_time > %s""",
            (issuer_entity, as_of, window_start),
        )
        purchases = cur.fetchall()
        if not purchases:
            return [], counts

        # One history query for the whole issuer rather than one per insider. Every
        # transaction code is fetched, not just purchases — a sell-every-March insider is as
        # scheduled as a buy-every-March one (opportunistic.py deviation 2) — and it is
        # filtered on knowable_time so the classification cannot see an unpublished filing.
        #
        # KEYED ON issuer_cik, NOT issuer_entity, and the difference is the whole measurement.
        # `issuer_entity` is this system's resolution artifact and is NULL on 94,775 of 759,698
        # rows — almost all of them 2021-2023, which is precisely the history a three-year
        # lookback has to reach through. Keying the lookup on it made the classifier blind to
        # the record it exists to read: measured 2026-09-15, entity-keyed history yields 1,833
        # opportunistic labels (3.0%) against cik-keyed 10,882 (17.9%), from the same rule on
        # the same trades. `issuer_cik` comes off the filing itself and is NOT NULL on every
        # row, so it identifies the issuer whether or not we resolved it to an entity.
        cur.execute(
            """SELECT owner_cik, event_time FROM insider_transactions
               WHERE issuer_cik = ANY(%s) AND knowable_time <= %s""",
            (sorted({p[2] for p in purchases}), as_of),
        )
        history: dict[str, list] = {}
        for owner, event_time in cur.fetchall():
            history.setdefault(owner, []).append(event_time)

    for tid, owner, _issuer_cik, shares, price, knowable, event_time in purchases:
        label = opportunistic.classify_insider(history.get(owner, []), event_time)
        counts[label] += 1
        if not opportunistic.counts_toward_gate(label):
            continue                       # routine: not a voice, and not a contribution
        magnitude = float(shares * price) if (shares is not None and price is not None) else None
        events.append(convergence.Event(
            subtype="insider_purchase", voice_key=f"insider:{owner}",
            knowable_time=knowable, magnitude=magnitude,
            ref={"table": "insider_transactions", "id": tid, "code": "P",
                 "classification": label},
        ))
    return events, counts


def compute_for_issuer(conn, issuer_entity: int, as_of: datetime,
                       params: dict) -> tuple[convergence.ClusterResult, dict]:
    events, counts = gather_events(conn, issuer_entity, as_of, params)
    return convergence.score_cluster(events, as_of, params), counts


def passes_liquidity_floor(conn, issuer_entity: int, as_of: datetime, params: dict) -> bool:
    """The same $2M 90-day median dollar volume floor convergence v3 uses, point-in-time.

    Delegated rather than reimplemented: two definitions of "liquid enough" would eventually
    disagree, and the comparison against v3 only means something if the floor is identical.
    """
    return convergence.passes_liquidity_floor(conn, issuer_entity, as_of, params)
