"""Alerts: the product reaches out (game-changer Slice B).

Pure decision functions turn already-gathered facts into notification records, each carrying a
stable dedup_key so the DB driver inserts exactly-once (ON CONFLICT (user_id, dedup_key) DO
NOTHING). Re-running the engine never double-notifies; a genuinely new cluster or filing (new id)
produces a new notification.

Delivery is tier-aware: a user is only ever alerted about signals their entitlement lets them see
(a free user's alerts respect the same 48h delay as the feed), so alerts can't be used to
exfiltrate fresh paid signals. Email is provider-agnostic and honest: a digest is queued into
email_outbox and marked 'sent' only when a real provider delivers it. None is configured in the
demo, so it stays 'queued' rather than pretending to send.
"""
from __future__ import annotations

import psycopg

from . import authn, config, presentation

DEFAULT_PREFS = {"new_high_conviction": True, "followed_activity": True, "min_score": 75, "email_enabled": False}
_ACTOR_ALERT = {  # event_kind -> (dedup prefix, title verb, notification kind)
    "insider": ("fa:i", "filed a Form 4 on", "followed_actor"),
    "stake":   ("fa:s", "filed a stake on", "followed_actor"),
    "holding": ("fa:h", "disclosed a position in", "followed_actor"),
}


# ------------------------------------------------------------------ pure planners

def high_conviction_notifications(clusters: list[dict], min_score: int) -> list[dict]:
    """One notification per cluster whose Smart Money Score is at/above the threshold."""
    out = []
    for c in clusters:
        if c["smart_money_score"] >= min_score:
            sym = c.get("symbol") or c.get("name") or "a company"
            out.append({
                "kind": "high_conviction",
                "title": f"\U0001F525 {sym}: smart money is converging (score {c['smart_money_score']})",
                "body": c.get("headline") or "Multiple independent smart-money sources are clustering.",
                "symbol": c.get("symbol"), "entity_id": c.get("entity_id"),
                "dedup_key": f"hc:{c['cluster_id']}",
            })
    return out


def followed_symbol_notifications(clusters: list[dict], followed_symbols: set[str]) -> list[dict]:
    """One notification per followed ticker that has a live cluster."""
    out = []
    for c in clusters:
        sym = (c.get("symbol") or "").upper()
        if sym and sym in followed_symbols:
            out.append({
                "kind": "followed_symbol",
                "title": f"⭐ {sym} you follow is converging — score {c['smart_money_score']}",
                "body": c.get("headline") or "New smart-money activity on a name you follow.",
                "symbol": c.get("symbol"), "entity_id": c.get("entity_id"),
                "dedup_key": f"fs:{c['cluster_id']}",
            })
    return out


def actor_notifications(events: list[dict]) -> list[dict]:
    """One notification per recent filing by a followed person/fund. `events` are already scoped
    to the user's follows and entitlement window by the caller."""
    out = []
    for e in events:
        prefix, verb, kind = _ACTOR_ALERT[e["event_kind"]]
        subj = e.get("symbol") or e.get("issuer_name") or "a company"
        when = f" ({e['date']})" if e.get("date") else ""
        out.append({
            "kind": kind,
            "title": f"\U0001F464 {e['actor_name']} {verb} {subj}{when}",
            "body": f"A smart-money actor you follow just filed on {subj}.",
            "symbol": e.get("symbol"), "entity_id": e.get("entity_id"),
            "dedup_key": f"{prefix}:{e['event_id']}",
        })
    return out


# ------------------------------------------------------------------ DB gather + driver

def _clusters_at(conn: psycopg.Connection, as_of) -> list[dict]:
    if as_of is None:
        return []
    with conn.cursor() as cur:
        cur.execute(
            """SELECT c.id, c.issuer_entity, c.score, c.inputs, e.name,
                      (SELECT symbol FROM security_map m WHERE m.entity_id=c.issuer_entity
                         AND m.source='sec_company_tickers' ORDER BY confidence DESC LIMIT 1)
               FROM signal_clusters c JOIN entities e ON e.id=c.issuer_entity WHERE c.as_of=%s""",
            (as_of,),
        )
        rows = cur.fetchall()
    out = []
    for cid, ent, score, inputs, name, sym in rows:
        story = presentation.cluster_story((inputs or {}).get("contributions", []), {})
        out.append({"cluster_id": cid, "entity_id": ent, "symbol": sym, "name": name,
                    "smart_money_score": presentation.smart_money_score(float(score)),
                    "headline": story["headline"]})
    return out


def _followed_actor_events(conn, user_id, eff_as_of, window_days=45, cap=8) -> list[dict]:
    events: list[dict] = []
    if eff_as_of is None:
        return events
    with conn.cursor() as cur:
        cur.execute("SELECT kind, ref FROM follows WHERE user_id=%s AND kind IN ('insider','filer')", (user_id,))
        ciks, filer_ids = [], []
        for kind, ref in cur.fetchall():
            if kind == "insider":
                ciks.append(ref)
            elif ref.isdigit():
                filer_ids.append(int(ref))
        if ciks:
            # collapse the many transaction lines of one Form 4 into a single alert per
            # (insider, issuer, day) so a multi-line filing does not fan out into a wall of alerts
            cur.execute(
                """SELECT q.owner_cik, q.owner_name, q.issuer_entity, q.issuer_name, q.sym, q.kn_day FROM (
                       SELECT DISTINCT ON (t.owner_cik, t.issuer_entity, t.knowable_time::date)
                              t.owner_cik, t.owner_name, t.issuer_entity, t.issuer_name,
                              (SELECT symbol FROM security_map m WHERE m.entity_id=t.issuer_entity AND m.source='sec_company_tickers' LIMIT 1) AS sym,
                              t.knowable_time::date AS kn_day
                       FROM insider_transactions t
                       WHERE t.owner_cik = ANY(%s) AND t.knowable_time <= %s
                         AND t.knowable_time > (SELECT max(knowable_time) FROM insider_transactions) - make_interval(days => %s)
                       ORDER BY t.owner_cik, t.issuer_entity, t.knowable_time::date DESC
                   ) q ORDER BY q.kn_day DESC LIMIT %s""",
                (ciks, eff_as_of, window_days, cap),
            )
            for cik, nm, ent, iss, sym, kn_day in cur.fetchall():
                events.append({"event_kind": "insider", "event_id": f"{cik}-{ent}-{kn_day}", "actor_name": nm,
                               "entity_id": ent, "issuer_name": iss, "symbol": sym, "date": kn_day})
        if filer_ids:
            cur.execute(
                """SELECT s.id, f.name, s.issuer_entity, e.name,
                          (SELECT symbol FROM security_map m WHERE m.entity_id=s.issuer_entity AND m.source='sec_company_tickers' LIMIT 1),
                          s.knowable_time::date
                   FROM stake_events s JOIN entities f ON f.id=s.filer_entity JOIN entities e ON e.id=s.issuer_entity
                   WHERE s.filer_entity = ANY(%s) AND s.knowable_time <= %s
                     AND s.knowable_time > (SELECT max(knowable_time) FROM stake_events) - make_interval(days => %s)
                   ORDER BY s.knowable_time DESC LIMIT %s""",
                (filer_ids, eff_as_of, window_days, cap),
            )
            for eid, nm, ent, iss, sym, kn_day in cur.fetchall():
                events.append({"event_kind": "stake", "event_id": eid, "actor_name": nm,
                               "entity_id": ent, "issuer_name": iss, "symbol": sym, "date": kn_day})
    return events


def _prefs_for(cur, user_id) -> dict:
    cur.execute("SELECT new_high_conviction, followed_activity, min_score, email_enabled FROM alert_prefs WHERE user_id=%s", (user_id,))
    r = cur.fetchone()
    if not r:
        return dict(DEFAULT_PREFS)
    return {"new_high_conviction": r[0], "followed_activity": r[1], "min_score": r[2], "email_enabled": r[3]}


def _insert_notifications(conn, user_id, notifs) -> list[dict]:
    inserted = []
    with conn.cursor() as cur:
        for n in notifs:
            cur.execute(
                """INSERT INTO notifications (user_id, kind, title, body, symbol, entity_id, dedup_key)
                   VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (user_id, dedup_key) DO NOTHING RETURNING id""",
                (user_id, n["kind"], n["title"], n["body"], n.get("symbol"), n.get("entity_id"), n["dedup_key"]),
            )
            if cur.fetchone():
                inserted.append(n)
    return inserted


def _queue_digest(conn, user_id, email, inserted) -> None:
    titles = "\n".join(f"- {n['title']}" for n in inserted[:10])
    n = len(inserted)
    subject = f"{config.brand_name()}: {n} new smart-money alert{'s' if n != 1 else ''}"
    body = f"You have {n} new alert(s):\n\n{titles}\n\nOpen {config.brand_name()} to see the details."
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO email_outbox (user_id, to_email, subject, body, status) VALUES (%s,%s,%s,%s,'queued')",
            (user_id, email, subject, body),
        )


def generate_alerts(conn: psycopg.Connection) -> dict:
    """Evaluate every user's alert rules against the signals they are entitled to see, and write
    any new notifications idempotently. Returns run counters."""
    counters = {"users": 0, "notifications_created": 0, "emails_queued": 0}
    with conn.cursor() as cur:
        cur.execute("SELECT id, email, tier FROM users")
        users = cur.fetchall()
        as_of_by_delay: dict[int, object] = {}
        for delay in {authn.delay_hours(t) for _, _, t in users}:
            cur.execute("SELECT max(as_of) FROM signal_clusters WHERE as_of <= now() - make_interval(hours => %s)", (delay,))
            as_of_by_delay[delay] = cur.fetchone()[0]
    clusters_by_delay = {d: _clusters_at(conn, aso) for d, aso in as_of_by_delay.items()}

    for uid, email, tier in users:
        counters["users"] += 1
        delay = authn.delay_hours(tier)
        clusters, eff_as_of = clusters_by_delay[delay], as_of_by_delay[delay]
        with conn.cursor() as cur:
            prefs = _prefs_for(cur, uid)
            cur.execute("SELECT ref FROM follows WHERE user_id=%s AND kind='symbol'", (uid,))
            followed_symbols = {r[0].upper() for r in cur.fetchall()}
        notifs: list[dict] = []
        if prefs["new_high_conviction"]:
            notifs += high_conviction_notifications(clusters, prefs["min_score"])
        if prefs["followed_activity"]:
            notifs += followed_symbol_notifications(clusters, followed_symbols)
            notifs += actor_notifications(_followed_actor_events(conn, uid, eff_as_of))
        inserted = _insert_notifications(conn, uid, notifs)
        counters["notifications_created"] += len(inserted)
        if inserted and prefs["email_enabled"]:
            _queue_digest(conn, uid, email, inserted)
            counters["emails_queued"] += 1
    conn.commit()
    return counters
