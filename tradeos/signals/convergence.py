"""Convergence signal v1.

Fires when many INDEPENDENT smart-money voices cluster on one issuer inside a rolling
window, computed strictly point-in-time (every input has knowable_time <= as_of). The
scoring is a pure function of a list of Events and the as_of, kept separate from the DB
gather so it is deterministic and offline-testable (the characterization test freezes a
fictional dataset and asserts exact scores).

Design properties (docs/threat-models/convergence.md):
  - independence collapse: a voice's strongest event counts fully, its extras at 25%, so
    single-origin echo cannot manufacture a score.
  - publish gate: >= min_voices distinct voices across >= min_source_classes classes.
  - freshness decay per class; insider sales score 0 (context); 13F scores only a genuine
    quarter-over-quarter new/increase, which needs >= 2 quarters (dormant on demo data).
  - all constants live in PARAMS (registered into the DB definition, version-locked).
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import psycopg

NAME = "convergence"

DEFAULT_PARAMS = {
    "window_days": 90,
    "base_weights": {
        "insider_purchase": 1.0,   # open-market purchase (code P, acquired)
        "insider_sale": 0.0,       # context only, not scored (decision #21)
        "stake_13d_new": 1.2,      # new activist stake
        "stake_13d_amend": 0.8,    # activist amendment (increase)
        "stake_13g": 0.6,          # passive >5% stake
        "holding_13f": 0.4,        # QoQ new/increase only; dormant on <2 quarters (decision #22)
    },
    "magnitude": {
        "insider_divisor": 6.0, "insider_cap": 1.5,   # log10(1+value)/6
        "stake_divisor": 10.0, "stake_cap": 1.5,      # percent_owned/10
        "holding_divisor": 8.0, "holding_cap": 1.2,   # log10(1+value_usd)/8
    },
    "half_life_days": {"insider": 14.0, "stake": 30.0, "holding": 60.0},
    "independence": {"secondary_weight": 0.25},
    "gate": {"min_source_classes": 2, "min_voices": 3},
    # v3 (decision #38): real liquidity floor — 90-day median dollar volume, point-in-time.
    # Sub-floor issuers do not publish at all (the illiquid names were the performance drag).
    "liquidity_floor_usd": 2000000.0,
    "liquidity_window_days": 90,
    # thresholds retained and validated against the liquid-universe backtest (score 3-6 -> +9.9%
    # mean excess, 6+ -> strong), not overfit to the small per-band sample.
    "buckets": {"low_max": 3.0, "medium_max": 6.0},   # <3 low, [3,6] medium, >6 high
}

CLASS_OF_SUBTYPE = {
    "insider_purchase": "insider", "insider_sale": "insider",
    "stake_13d_new": "activist", "stake_13d_amend": "activist",
    "stake_13g": "passive_stake", "holding_13f": "institutional_holding",
}
_DECAY_GROUP = {  # which half-life a class uses
    "insider": "insider", "activist": "stake", "passive_stake": "stake",
    "institutional_holding": "holding",
}


def module_code_hash() -> str:
    """sha256 of this module's source. Any change to logic or PARAMS changes this, which
    forces a new registered definition before compute-signals will run (decision #24)."""
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


@dataclass(frozen=True)
class Event:
    subtype: str                 # key into base_weights
    voice_key: str               # 'insider:<cik>' or 'filer:<entity_id>'
    knowable_time: datetime      # tz-aware
    magnitude: float | None      # trade value USD | percent owned | 13F value USD
    ref: dict = field(default_factory=dict)   # ids/labels for the inputs jsonb


@dataclass
class ClusterResult:
    score: float
    voices: int
    source_classes: list[str]
    passes_gate: bool
    contributions: list[dict]
    context: list[dict]
    freshest_knowable: datetime | None
    stalest_knowable: datetime | None


def _magnitude_scale(subtype: str, magnitude: float | None, p: dict) -> float:
    cls = CLASS_OF_SUBTYPE[subtype]
    m = p["magnitude"]
    if magnitude is None or magnitude <= 0:
        return 1.0  # unknown magnitude is neutral, never amplified nor zeroed
    if cls == "insider":
        return min(m["insider_cap"], math.log10(1 + magnitude) / m["insider_divisor"])
    if cls in ("activist", "passive_stake"):
        return min(m["stake_cap"], magnitude / m["stake_divisor"])
    if cls == "institutional_holding":
        return min(m["holding_cap"], math.log10(1 + magnitude) / m["holding_divisor"])
    return 1.0


def _decay(subtype: str, knowable: datetime, as_of: datetime, p: dict) -> float:
    hl = p["half_life_days"][_DECAY_GROUP[CLASS_OF_SUBTYPE[subtype]]]
    age_days = max(0.0, (as_of - knowable).total_seconds() / 86400.0)
    return 0.5 ** (age_days / hl)


def decayed_weight(ev: Event, as_of: datetime, p: dict) -> float:
    base = p["base_weights"].get(ev.subtype, 0.0)
    if base == 0.0:
        return 0.0
    return base * _magnitude_scale(ev.subtype, ev.magnitude, p) * _decay(ev.subtype, ev.knowable_time, as_of, p)


def score_cluster(events: list[Event], as_of: datetime, params: dict | None = None) -> ClusterResult:
    """Pure, deterministic. Independence collapse by voice, then gate + freshness summary."""
    p = params or DEFAULT_PARAMS
    contributions: list[dict] = []
    context: list[dict] = []
    by_voice: dict[str, list[float]] = {}

    for ev in events:
        if ev.knowable_time > as_of:
            continue  # look-ahead guard (v2): not yet knowable at as_of, never counted
        w = decayed_weight(ev, as_of, p)
        cls = CLASS_OF_SUBTYPE[ev.subtype]
        row = {
            "subtype": ev.subtype, "source_class": cls, "voice": ev.voice_key,
            "knowable_time": ev.knowable_time.isoformat(), "magnitude": ev.magnitude,
            "decayed_weight": round(w, 6), **ev.ref,
        }
        if w > 0:
            contributions.append(row)
            by_voice.setdefault(ev.voice_key, []).append(w)
        else:
            context.append(row)

    score = 0.0
    for weights in by_voice.values():
        ws = sorted(weights, reverse=True)
        score += ws[0] + p["independence"]["secondary_weight"] * sum(ws[1:])

    source_classes = sorted({c["source_class"] for c in contributions})
    voices = len(by_voice)
    passes_gate = (len(source_classes) >= p["gate"]["min_source_classes"]
                   and voices >= p["gate"]["min_voices"])

    knowables = [ev.knowable_time for ev in events
                 if ev.knowable_time <= as_of and decayed_weight(ev, as_of, p) > 0]
    freshest = max(knowables) if knowables else None
    stalest = min(knowables) if knowables else None
    return ClusterResult(round(score, 6), voices, source_classes, passes_gate,
                         contributions, context, freshest, stalest)


def bucket_for(score: float, floor_ok: bool, p: dict) -> str:
    """Below the liquidity floor is forced 'low' (excluded from the default feed)."""
    if not floor_ok:
        return "low"
    if score < p["buckets"]["low_max"]:
        return "low"
    if score <= p["buckets"]["medium_max"]:
        return "medium"
    return "high"


# ------------------------------------------------------------------ DB gather

def _passes_liquidity_floor(cur, issuer_entity: int, as_of: datetime, params: dict) -> bool:
    """Liquidity floor (decision #38): 90-day median dollar volume above the threshold,
    computed point-in-time (prices on/before as_of). No price history -> below floor."""
    cur.execute(
        """SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY p.close * p.volume)
           FROM prices_eod p JOIN security_map m ON m.symbol = p.symbol
           WHERE m.entity_id = %s AND m.source = 'sec_company_tickers'
             AND p.volume IS NOT NULL AND p.day <= %s::date AND p.day > %s::date - %s""",
        (issuer_entity, as_of, as_of, params["liquidity_window_days"]),
    )
    mdv = cur.fetchone()[0]
    return mdv is not None and mdv >= params["liquidity_floor_usd"]


def gather_events(conn: psycopg.Connection, issuer_entity: int, as_of: datetime, params: dict) -> list[Event]:
    window_start = as_of - timedelta(days=params["window_days"])
    events: list[Event] = []
    with conn.cursor() as cur, conn.cursor() as cur2:
        # insider transactions
        cur.execute(
            """SELECT id, owner_cik, transaction_code, acquired_disposed, shares, price_per_share, knowable_time
               FROM insider_transactions
               WHERE issuer_entity = %s AND knowable_time <= %s AND knowable_time > %s""",
            (issuer_entity, as_of, window_start),
        )
        for tid, owner, code, ad, shares, price, kn in cur.fetchall():
            purchase = (code == "P" and ad == "A")
            magnitude = float(shares * price) if (purchase and shares is not None and price is not None) else None
            events.append(Event(
                subtype="insider_purchase" if purchase else "insider_sale",
                voice_key=f"insider:{owner}", knowable_time=kn, magnitude=magnitude,
                ref={"table": "insider_transactions", "id": tid, "code": code},
            ))

        # 13D/13G stakes
        cur.execute(
            """SELECT id, filer_entity, form_type, percent_owned, knowable_time
               FROM stake_events
               WHERE issuer_entity = %s AND knowable_time <= %s AND knowable_time > %s""",
            (issuer_entity, as_of, window_start),
        )
        for sid, filer, form_type, pct, kn in cur.fetchall():
            if form_type == "SCHEDULE 13D":
                subtype = "stake_13d_new"
            elif form_type == "SCHEDULE 13D/A":
                subtype = "stake_13d_amend"
            else:  # SCHEDULE 13G / 13G/A
                subtype = "stake_13g"
            events.append(Event(
                subtype=subtype, voice_key=f"filer:{filer}", knowable_time=kn,
                magnitude=float(pct) if pct is not None else None,
                ref={"table": "stake_events", "id": sid, "form_type": form_type},
            ))

        # 13F holdings — scored only as a genuine QoQ new/increase (needs a prior quarter)
        cur.execute(
            """SELECT id, filer_entity, value_usd, shares, period_end, knowable_time
               FROM fund_holdings
               WHERE issuer_entity = %s AND knowable_time <= %s AND knowable_time > %s""",
            (issuer_entity, as_of, window_start),
        )
        for hid, filer, value, shares, period_end, kn in cur.fetchall():
            cur2.execute(
                """SELECT max(period_end) FROM fund_holdings
                   WHERE filer_entity = %s AND period_end < %s AND knowable_time <= %s""",
                (filer, period_end, as_of),
            )
            prior_period = cur2.fetchone()[0]
            if prior_period is None:
                continue  # decision #22: cannot establish new/increase without a prior quarter
            cur2.execute(
                "SELECT coalesce(sum(shares), 0) FROM fund_holdings WHERE filer_entity = %s AND issuer_entity = %s AND period_end = %s",
                (filer, issuer_entity, prior_period),
            )
            prior_shares = cur2.fetchone()[0]
            is_new_or_increase = shares is not None and (prior_shares == 0 or shares > prior_shares)
            if is_new_or_increase:
                events.append(Event(
                    subtype="holding_13f", voice_key=f"filer:{filer}", knowable_time=kn,
                    magnitude=float(value) if value is not None else None,
                    ref={"table": "fund_holdings", "id": hid, "prior_shares": float(prior_shares)},
                ))
    return events


def candidate_issuers(conn: psycopg.Connection, as_of: datetime, params: dict) -> list[int]:
    window_start = as_of - timedelta(days=params["window_days"])
    with conn.cursor() as cur:
        cur.execute(
            """SELECT DISTINCT issuer_entity FROM (
                   SELECT issuer_entity, knowable_time FROM insider_transactions
                   UNION ALL SELECT issuer_entity, knowable_time FROM stake_events
                   UNION ALL SELECT issuer_entity, knowable_time FROM fund_holdings
               ) t
               WHERE issuer_entity IS NOT NULL AND knowable_time <= %s AND knowable_time > %s""",
            (as_of, window_start),
        )
        return [r[0] for r in cur.fetchall()]


def compute_for_issuer(conn, issuer_entity, as_of, params) -> ClusterResult:
    events = gather_events(conn, issuer_entity, as_of, params)
    return score_cluster(events, as_of, params)


def passes_liquidity_floor(conn, issuer_entity, as_of, params) -> bool:
    """Public wrapper — the caller checks this only for gate-passing clusters (the floor query
    is a per-issuer median, so we avoid running it on the thousands of non-clustering candidates)."""
    with conn.cursor() as cur:
        return _passes_liquidity_floor(cur, issuer_entity, as_of, params)
