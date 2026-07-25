"""Smart-money convergence signals, expressed as scoreable claims.

The brief is explicit: "feed all of it into the same claim and Ledger machinery so its signals get
scored like everything else". This does that. It is also the only way the Ledger gets meaningful
numbers this decade — the interpretive engine's claims are days old and the shortest horizon is a
working week, whereas the signal plane has 593 measured outcomes going back to November 2024.

**On backdating, because this is the one place it could look like cheating.**

These claims carry the timestamp of the signal cluster's `as_of`, not the moment of import. That is
honest, and the distinction matters:

  * The signal genuinely existed at that time. `signal_clusters` is computed under strict
    point-in-time discipline — every input is filtered by `knowable_time`, so a cluster dated
    2025-03-14 used only information public on 2025-03-14. The system really did make that call
    then.
  * The outcomes were measured by the existing backtest against prices strictly AFTER entry, with
    the same excess-vs-SPY method the Ledger uses.

What would be dishonest is presenting these as interpretations the impact engine made. So they are
marked `model_version = 'convergence-vN'` rather than a model name, and the Ledger's by-source
breakdown keeps them separable from LLM-generated claims. A reader can always ask "how does the
model do on its own?" and get an answer.

**The mechanism is structural, so no model is involved.** Why clustered insider buying might
matter is a known argument, not something to be reasoned out per case — which makes it exactly the
kind of thing that should be written once, in code, rather than generated.
"""
from __future__ import annotations

import logging

from psycopg.types.json import Json

log = logging.getLogger("tradeos.smartmoney_claims")

# The signal's own horizons, in trading days, matching the backtest's measurement windows.
HORIZON_DAYS = {30: "months", 90: "months"}

# Confidence per bucket. Deliberately modest and NOT flattering: the published backtest shows a
# ~42% hit rate at 30 days with slightly negative average excess, so claiming high confidence here
# would be contradicted by our own Ledger the moment anyone looked.
BUCKET_CONFIDENCE = {"high": 0.55, "medium": 0.45, "low": 0.38}

LAG_NOTE = (
    "13F institutional holdings are disclosed up to 45 days after the quarter ends, so a position "
    "shown here may already have changed. Form 4 insider transactions are far fresher — typically "
    "two business days."
)


def mechanism(voices: int, classes: list[str], symbol: str | None) -> str:
    """Why clustered smart-money activity might matter, stated as a causal channel.

    Written once rather than generated, because the argument does not change per case — and a
    model asked to re-derive it every time would eventually produce a version that overstates it."""
    who = []
    if "insider" in classes:
        who.append("company insiders buying on the open market")
    if "activist" in classes or "13d" in classes:
        who.append("investors filing activist stakes")
    if "institution" in classes or "13f" in classes:
        who.append("institutions disclosing 5%+ holdings")
    actors = ", and ".join(who) if who else "multiple filers"
    name = symbol or "this issuer"
    return (
        f"{voices} separate filers acted on {name} inside a short window — {actors}. The channel "
        "is informational asymmetry: insiders and large holders observe order books, hiring, "
        "renewals and pipeline before any of it reaches a public number, and a purchase is the "
        "costliest way to express that view. Clustering matters more than any single filing "
        "because one purchase can be a liquidity event or a scheduled plan, whereas several "
        "independent parties acting within days of each other is harder to explain that way. "
        "The effect is expected to show up over weeks to months as the information becomes "
        "public through ordinary reporting, not immediately."
    )


def build(conn, horizon_days: int = 30, since: str | None = None, limit: int = 2000) -> dict:
    """Create a claim per historical signal cluster, and import its measured outcome.

    Idempotent: a cluster already imported is skipped, so re-running never inflates the record."""
    model_version = _definition_version(conn)
    made, scored, skipped = 0, 0, 0
    with conn.cursor() as cur:
        cur.execute(
            """SELECT c.id, c.as_of, c.confidence_bucket, c.issuer_entity, c.voices, c.source_classes,
                      o.entry_day, o.excess_30, o.excess_90,
                      (SELECT symbol FROM security_map m WHERE m.entity_id = c.issuer_entity
                         AND m.source = 'sec_company_tickers' ORDER BY confidence DESC LIMIT 1),
                      e.name
                 FROM signal_clusters c
                 JOIN signal_outcomes o ON o.cluster_id = c.id
                 LEFT JOIN entities e ON e.id = c.issuer_entity
                WHERE o.excess_30 IS NOT NULL
                  AND (%s::date IS NULL OR c.as_of::date >= %s::date)
             ORDER BY c.as_of LIMIT %s""", (since, since, limit))
        rows = cur.fetchall()

        for (cid, as_of, bucket, _issuer, voices, classes, entry_day,
             ex30, ex90, symbol, name) in rows:
            if not symbol:
                skipped += 1          # nothing scoreable without a ticker
                continue
            # Provenance lives in source_ref, never in the prose — an earlier version appended
            # the key to the mechanism and put an internal identifier in front of every reader.
            external = f"convergence:{cid}:{horizon_days}"
            cur.execute("SELECT 1 FROM claims WHERE source_ref = %s", (external,))
            if cur.fetchone():
                continue

            excess = ex30 if horizon_days == 30 else ex90
            if excess is None:
                skipped += 1
                continue

            n_voices = int(voices or 1) if isinstance(voices, (int, float)) else len(voices or [])
            body = mechanism(n_voices, list(classes or []), symbol)
            cur.execute(
                """INSERT INTO claims (event_id, cluster_id, created_at, model_version, mechanism,
                                       affected, horizon, horizon_days, confidence, analogs,
                                       reasoning_trace, resolved_at, status, source_ref)
                   VALUES (NULL, NULL, %s, %s, %s, %s, %s, %s, %s, '[]', %s, now(), 'resolved', %s)
                   RETURNING id""",
                (as_of, model_version, body,
                 Json([{"kind": "asset", "value": symbol, "direction": "up",
                        "magnitude": "moderate"}]),
                 HORIZON_DAYS.get(horizon_days, "months"), horizon_days,
                 BUCKET_CONFIDENCE.get(bucket, 0.4),
                 Json([f"{n_voices} filers acted on {name or symbol} within a short window",
                       "clustered activity is harder to explain as one party's liquidity event",
                       f"measured against SPY over {horizon_days} days"]),
                 external))
            claim_id = cur.fetchone()[0]
            made += 1

            # The outcome as the existing backtest measured it — same excess-vs-SPY method the
            # Ledger uses, so importing it is not mixing two yardsticks.
            from .ledger import verdict_for
            verdict, note = verdict_for("up", float(excess))
            cur.execute(
                """INSERT INTO claim_outcomes (claim_id, subject, predicted, magnitude, entry_day,
                                               excess_return, verdict, note)
                   VALUES (%s,%s,'up','moderate',%s,%s,%s,%s)
                   ON CONFLICT (claim_id, subject) DO NOTHING""",
                (claim_id, symbol, entry_day, float(excess), verdict,
                 note or "measured by the signal backtest, excess vs SPY"))
            scored += 1
    conn.commit()
    log.info("smartmoney_claims: %d made, %d scored, %d skipped", made, scored, skipped)
    return {"claims_made": made, "outcomes_imported": scored, "skipped": skipped,
            "model_version": model_version, "lag_note": LAG_NOTE}


def _definition_version(conn) -> str:
    with conn.cursor() as cur:
        cur.execute("SELECT max(version) FROM signal_definitions")
        row = cur.fetchone()
    return f"convergence-v{row[0]}" if row and row[0] else "convergence"
