"""Public, unauthenticated reads for the marketing site (Phase 7).

Its own module rather than more routes in `app.py`, because these have a property none of the app's
routes have: **they are served to anyone, with no session, and are the only endpoints a search
engine or a stranger will ever hit.** Keeping that boundary in one file makes it possible to answer
"what does an anonymous caller see?" by reading a single page.

Two rules hold here that the rest of the API can relax:

  * **No user-scoped data, ever.** Nothing in this module accepts a session, reads `users`,
    `trades`, `watchlists` or `user_profiles`, or takes an identifier that could address a person.
    The country preview takes an ISO code and scores against the *published* exposure reference
    data, so it personalises without a person.

  * **Nothing may be cherry-picked to flatter.** The walkthrough rotates deterministically by day
    over the real store rather than being chosen for how well it went, and the settled example it
    shows alongside is drawn newest-first, not best-first. A marketing surface that filtered for
    wins would make the Ledger — which leads with its misses — a lie by omission.
"""
from __future__ import annotations

import logging
from datetime import date

from . import relevance

log = logging.getLogger("tradeos.public_site")

WALKTHROUGH_POOL = 12       # rotate over the N freshest live interpretations, one per day


def _claim_row(r) -> dict:
    cols = ("id", "created_at", "mechanism", "affected", "horizon", "horizon_days", "confidence",
            "model_version", "headline", "source", "url", "geo", "category", "novelty")
    d = dict(zip(cols, r, strict=True))
    d["created_at"] = d["created_at"].isoformat()
    return d


_LIVE_SQL = """
    SELECT c.id, c.created_at, c.mechanism, c.affected, c.horizon, c.horizon_days, c.confidence,
           c.model_version, e.title, e.source, e.source_url, e.geo, e.category, cl.novelty_score
      FROM claims c
      JOIN events e ON e.id = c.event_id
      LEFT JOIN event_clusters cl ON cl.id = c.cluster_id
     WHERE c.status = 'open'
  ORDER BY c.created_at DESC
     LIMIT %s
"""


def live_claims(conn, limit: int = 6) -> list[dict]:
    """The freshest open interpretations that came from a real world event.

    Event-derived only. A convergence signal is a real claim and it is scored in the Ledger like
    everything else, but the hero's promise is "watch it interpret something that happened this
    morning", and a 13F filing is not that.
    """
    with conn.cursor() as cur:
        cur.execute(_LIVE_SQL, (max(1, min(20, limit)),))
        return [_claim_row(r) for r in cur.fetchall()]


def _settled(conn) -> dict | None:
    """One already-marked call, newest first, with what actually happened to it.

    Deliberately not filtered by verdict. This is the proof that the loop closes, and if it only
    ever showed hits it would be proof of the opposite.
    """
    with conn.cursor() as cur:
        cur.execute(
            """SELECT c.id, c.mechanism, c.confidence, c.horizon, c.created_at, c.resolved_at,
                      o.subject, o.predicted, o.verdict, o.excess_return, o.actual_return
                 FROM claims c JOIN claim_outcomes o ON o.claim_id = c.id
                WHERE c.status = 'resolved' AND o.verdict IN ('hit', 'miss')
             ORDER BY c.resolved_at DESC NULLS LAST, c.id DESC
                LIMIT 1""")
        r = cur.fetchone()
    if not r:
        return None
    return {"claim_id": r[0], "mechanism": r[1], "confidence": float(r[2]), "horizon": r[3],
            "made_on": r[4].date().isoformat(), "marked_on": r[5].date().isoformat() if r[5] else None,
            "subject": r[6], "predicted": r[7], "verdict": r[8],
            "excess_return": round(float(r[9]), 4) if r[9] is not None else None,
            "actual_return": round(float(r[10]), 4) if r[10] is not None else None}


def walkthrough(conn, today: date | None = None) -> dict:
    """One real interpretation, walked end to end, rotating by day over the live store.

    `today.toordinal() % pool` rather than "the most interesting one": the brief asks for a daily
    walkthrough from the actual store, and any selection rule that could be tuned toward a good
    example is a selection rule that eventually will be.

    The honest shape of this section is set by the data rather than by what would sell best. Every
    resolved outcome in the store today belongs to a convergence signal; the event-derived claims
    were made recently and their horizons have not elapsed. So the walk ends on *when this gets
    marked*, not on a result — and `settled` carries a separate, genuinely finished call so a
    visitor can see that the last step really does happen.
    """
    today = today or date.today()
    pool = live_claims(conn, WALKTHROUGH_POOL)
    if not pool:
        return {"available": False,
                "reason": "No live interpretations in the store right now."}
    c = pool[today.toordinal() % len(pool)]

    made = date.fromisoformat(c["created_at"][:10])
    scores_on = date.fromordinal(made.toordinal() + int(c["horizon_days"]))
    return {
        "available": True,
        "claim": c,
        "scores_on": scores_on.isoformat(),
        "days_remaining": max(0, (scores_on - today).days),
        "settled": _settled(conn),
        "rotates": "one interpretation per day, taken in order from the live store",
    }


def frame_preview(conn, country: str | None, limit: int = 5) -> dict:
    """The same day, read from one country — the personalisation demo, without an account.

    Scores the live interpretations against that country's published exposure row using exactly the
    ranking the product uses for a signed-in reader, minus the watchlist (a stranger has none). The
    country list is the hand-curated reference data and nothing else: offering a visitor a country
    the product has no sourced exposure figures for would be inventing a perspective to demo it.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT country, name, currency, main_index FROM country_exposure ORDER BY name")
        available = [{"country": r[0], "name": r[1], "currency": r[2], "main_index": r[3]}
                     for r in cur.fetchall()]
        known = {c["country"] for c in available}

        code = (country or "").upper() or None
        if code and code not in known:
            return {"countries": available, "country": None,
                    "error": f"No sourced exposure data for {code} yet — the reference set is "
                             f"deliberately small and hand-checked rather than interpolated."}

        exposure, profile = None, None
        if code:
            cur.execute("""SELECT currency, currency_regime, pegged_to, export_partners,
                                  import_partners, commodity_exposure
                             FROM country_exposure WHERE country = %s""", (code,))
            e = cur.fetchone()
            if e:
                exposure = {"currency": e[0], "currency_regime": e[1], "pegged_to": e[2],
                            "export_partners": e[3], "import_partners": e[4],
                            "commodity_exposure": e[5]}
                profile = {"country": code, "base_currency": e[0]}

    ranked = []
    for c in live_claims(conn, 40):
        scored = relevance.score(c, profile, exposure, set(), c.get("novelty"))
        ranked.append({"id": c["id"], "headline": c["headline"], "category": c["category"],
                       "horizon": c["horizon"], "confidence": c["confidence"],
                       "affected": c["affected"], "source": c["source"],
                       **scored, "why_shown": relevance.explain(scored["parts"])})
    ranked.sort(key=lambda x: x["relevance"], reverse=True)

    meta = next((c for c in available if c["country"] == code), None)
    return {"countries": available, "country": meta, "claims": ranked[:max(1, min(10, limit))],
            "note": ("Ranked with the same scoring a signed-in reader gets, without a watchlist. "
                     "Confidence, geography, currency exposure and novelty; no model involved.")}
