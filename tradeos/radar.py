"""Saved filter sets, threading, and subscribable alerts — the Phase 4 remainder.

Three things the brief asked for on the Radar and that were carried as outstanding through five
later phases.

**Threading.** *"When an event develops over days, the card updates in place with a visible history
of how the interpretation changed... Users should be able to watch the system change its mind and
see why."* The clustering substrate already existed; what was missing is that a cluster was
interpreted once and never again, so a developing story never got a second reading. `thread()`
assembles the chain, and `claims.reinterpret_developing` produces the revisions.

The rule that makes this honest is in migration 032 and worth repeating: **a superseded claim is
still scored.** Revising is not withdrawing. If a revision removed the original from the Ledger,
changing its mind would be a mechanism for erasing misses.

**Saved filter sets.** A spec is validated into a fixed shape before it is stored, so a filter is
never a place where arbitrary structure reaches a query. Matching is pure and runs in Python over
already-fetched claims rather than being compiled into SQL — the Radar's page size is bounded, and
a user-defined predicate that becomes a WHERE clause is a much larger surface than this is worth.

**Subscriptions.** Throttled hard, with a high-water mark so a retry can never resend. Webhook
delivery is the sharpest thing in this file: the URL is supplied by the user and fetched by the
server, which is the definition of SSRF. `_webhook_target_ok` is the whole defence and its
reasoning is written out there.
"""
from __future__ import annotations

import ipaddress
import json
import logging
import socket
from urllib.parse import urlsplit

import httpx
import psycopg
from psycopg import sql
from psycopg.types.json import Json

log = logging.getLogger("tradeos.radar")

HORIZONS = ("hours", "days", "weeks", "months")
MAX_FILTERS = 20            # per user; a filter list is a menu, not a database
MIN_THROTTLE_MINS = 60
ALERT_BATCH = 10            # claims named in one notification


# ------------------------------------------------------------------ pure: the filter spec

def normalise_spec(raw: dict | None) -> dict:
    """Coerce whatever arrived into the fixed shape, dropping anything unrecognised.

    An allowlist, not a sanitiser. The stored spec can only ever contain these five keys with
    these types, so `matches()` never has to defend itself and no future caller can be surprised
    by a spec that carries something else."""
    raw = raw if isinstance(raw, dict) else {}

    def strings(key, cap=20, upper=False):
        vals = raw.get(key)
        if not isinstance(vals, list):
            return []
        out = []
        for v in vals:
            s = str(v).strip()[:40]
            if upper:
                s = s.upper()
            if s and s not in out:
                out.append(s)
        return out[:cap]

    try:
        floor = float(raw.get("min_confidence") or 0.0)
    except (TypeError, ValueError):
        floor = 0.0

    return {
        "categories": strings("categories"),
        "geo": strings("geo", cap=30, upper=True),
        "horizons": [h for h in strings("horizons") if h in HORIZONS],
        "sources": strings("sources", cap=20),
        "min_confidence": min(1.0, max(0.0, floor)),
    }


def matches(claim: dict, spec: dict) -> bool:
    """Does one claim belong in this stream? Empty list for a dimension means "no constraint",
    which is what makes a fresh filter show everything rather than nothing."""
    if float(claim.get("confidence") or 0) < spec.get("min_confidence", 0.0):
        return False
    cats = spec.get("categories") or []
    if cats and (claim.get("category") or "") not in cats:
        return False
    hors = spec.get("horizons") or []
    if hors and (claim.get("horizon") or "") not in hors:
        return False
    srcs = spec.get("sources") or []
    if srcs and (claim.get("source") or "") not in srcs:
        return False
    geo = spec.get("geo") or []
    if geo:
        # What the claim AFFECTS, not who published it — the distinction `relevance.places()`
        # exists to hold. A filter keyed on the outlet's country would be the same mistake again.
        from . import relevance
        if not (set(relevance.places(claim)) & set(geo)):
            return False
    return True


# ------------------------------------------------------------------ pure: threading

def thread(claims: list[dict]) -> list[dict]:
    """Collapse a claim list into threads: one entry per developing story, newest reading first.

    Claims on the same cluster are the same story. The newest is the current interpretation; the
    rest are its history, and they are RETURNED rather than hidden — the point of threading here is
    that a reader can watch the system change its mind, which requires seeing what it used to say.

    `changed` summarises what actually moved between the current reading and the one before it, so
    the interface can lead with that instead of making the reader diff two paragraphs.
    """
    by_cluster: dict = {}
    loose: list[dict] = []
    for c in claims:
        cid = c.get("cluster_id")
        if cid is None:
            loose.append({**c, "history": [], "revisions": 0})
        else:
            by_cluster.setdefault(cid, []).append(c)

    out = list(loose)
    for group in by_cluster.values():
        group = sorted(group, key=lambda x: (x.get("created_at") or "", x.get("id") or 0), reverse=True)
        head, history = group[0], group[1:]
        entry = {**head, "history": history, "revisions": len(history)}
        if history:
            entry["changed"] = _what_changed(history[0], head)
        out.append(entry)

    out.sort(key=lambda x: x.get("relevance", 0), reverse=True)
    return out


def _direction_of(claim: dict) -> dict:
    return {str(a.get("value", "")).upper(): a.get("direction")
            for a in (claim.get("affected") or []) if a.get("kind") == "asset"}


def _what_changed(before: dict, after: dict) -> dict:
    """A plain diff of two readings of the same story. Only the things a reader would care about:
    did the confidence move, did it change its mind about a direction, did it name something new."""
    b_conf, a_conf = float(before.get("confidence") or 0), float(after.get("confidence") or 0)
    b_dir, a_dir = _direction_of(before), _direction_of(after)

    reversed_on = sorted(s for s in (b_dir.keys() & a_dir.keys()) if b_dir[s] != a_dir[s])
    added = sorted(a_dir.keys() - b_dir.keys())
    dropped = sorted(b_dir.keys() - a_dir.keys())

    notes = []
    if abs(a_conf - b_conf) >= 0.05:
        notes.append(f"confidence moved from {round(b_conf * 100)}% to {round(a_conf * 100)}%")
    if reversed_on:
        notes.append("reversed direction on " + ", ".join(reversed_on))
    if added:
        notes.append("now also names " + ", ".join(added))
    if dropped:
        notes.append("no longer names " + ", ".join(dropped))
    if not notes:
        notes.append("the reading held; more sources corroborated it")

    return {"confidence_from": round(b_conf, 3), "confidence_to": round(a_conf, 3),
            "reversed": reversed_on, "added": added, "dropped": dropped,
            "summary": "; ".join(notes)}


# ------------------------------------------------------------------ SSRF defence

# Blocked destinations for a user-supplied webhook. This is the whole defence, so it is written
# out rather than delegated.
#
# The user gives a URL and the server fetches it, which is SSRF by construction. The danger is not
# the public internet — it is that the server can reach things the user cannot: a metadata service
# on 169.254.169.254 holding cloud credentials, a database on a private subnet, another container
# by name, localhost.
#
# Resolution is done HERE and the resolved IP is what gets checked, because checking the hostname
# alone loses to a DNS record that points at 127.0.0.1. Every address the name resolves to must be
# acceptable, not just the first — a name resolving to one public and one private address would
# otherwise pass and then connect wherever the client picked.
_BLOCKED_PORTS = {22, 23, 25, 445, 3306, 5432, 6379, 9200, 11211, 27017}


def webhook_target_ok(url: str) -> tuple[bool, str]:
    """(allowed, reason). Refuses anything that could reach infrastructure rather than the user."""
    try:
        parts = urlsplit(url)
    except Exception:
        return False, "that is not a URL"

    if parts.scheme != "https":
        # http would also send the payload in the clear across whatever network sits between.
        return False, "the webhook URL must be https"
    host = parts.hostname
    if not host:
        return False, "the webhook URL has no host"
    if parts.port and parts.port in _BLOCKED_PORTS:
        return False, f"port {parts.port} is not a webhook endpoint"

    try:
        infos = socket.getaddrinfo(host, parts.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return False, "that host does not resolve"

    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified):
            return False, "that host resolves to a private or reserved address"
    return True, ""


# ------------------------------------------------------------------ DB: saved filters

def _row(r) -> dict:
    return {"id": r[0], "name": r[1], "spec": r[2], "subscribed": r[3], "channel": r[4],
            "webhook_url": r[5], "throttle_mins": r[6],
            "last_sent_at": r[7].isoformat() if r[7] else None}


# Composed, not interpolated. These are fixed internal identifiers and were never attacker
# controlled — but ruff's S608 was re-enabled in Phase 9 precisely so new code cannot reopen the
# question, and it caught this file on the first lint. That is the rule working.
_COL_NAMES = ("id", "name", "spec", "subscribed", "channel", "webhook_url", "throttle_mins",
              "last_sent_at")
_COLS = sql.SQL(", ").join(sql.Identifier(c) for c in _COL_NAMES)


def listing(conn: psycopg.Connection, user_id: int) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(sql.SQL("SELECT {cols} FROM radar_filters WHERE user_id=%s "
                            "ORDER BY name").format(cols=_COLS), (user_id,))
        return [_row(r) for r in cur.fetchall()]


def save(conn: psycopg.Connection, user_id: int, name: str, spec: dict, subscribed: bool = False,
         channel: str | None = None, webhook_url: str | None = None,
         throttle_mins: int = 360) -> dict:
    name = (name or "").strip()[:60]
    if not name:
        return {"error": "give the filter a name"}

    channel = channel if channel in ("email", "webhook") else None
    throttle = max(MIN_THROTTLE_MINS, int(throttle_mins or 360))

    if subscribed:
        if not channel:
            return {"error": "choose email or webhook to subscribe"}
        if channel == "webhook":
            ok, why = webhook_target_ok(webhook_url or "")
            if not ok:
                return {"error": why}
        else:
            webhook_url = None
    else:
        channel, webhook_url = None, None

    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM radar_filters WHERE user_id=%s AND name<>%s", (user_id, name))
        if cur.fetchone()[0] >= MAX_FILTERS:
            return {"error": f"you can keep {MAX_FILTERS} saved filters"}
        cur.execute(
            sql.SQL("""INSERT INTO radar_filters (user_id, name, spec, subscribed, channel,
                                                  webhook_url, throttle_mins)
                       VALUES (%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (user_id, name) DO UPDATE SET
                           spec=EXCLUDED.spec, subscribed=EXCLUDED.subscribed,
                           channel=EXCLUDED.channel, webhook_url=EXCLUDED.webhook_url,
                           throttle_mins=EXCLUDED.throttle_mins, updated_at=now()
                       RETURNING {cols}""").format(cols=_COLS),
            (user_id, name, Json(normalise_spec(spec)), subscribed, channel, webhook_url, throttle))
        out = _row(cur.fetchone())
    conn.commit()
    return {"saved": True, "filter": out}


def delete(conn: psycopg.Connection, user_id: int, filter_id: int) -> dict:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM radar_filters WHERE id=%s AND user_id=%s", (filter_id, user_id))
        removed = bool(cur.rowcount)
    conn.commit()
    return {"removed": removed}


# ------------------------------------------------------------------ DB: delivering subscriptions

def _claims_since(cur, since_id: int | None, limit: int = 200) -> list[dict]:
    cur.execute(
        """SELECT c.id, c.created_at, c.mechanism, c.affected, c.horizon, c.confidence,
                  c.cluster_id, e.title, e.source, e.source_url, e.geo, e.category
             FROM claims c LEFT JOIN events e ON e.id = c.event_id
            WHERE c.id > %s
         ORDER BY c.id LIMIT %s""", (since_id or 0, limit))
    cols = ("id", "created_at", "mechanism", "affected", "horizon", "confidence", "cluster_id",
            "headline", "source", "url", "geo", "category")
    rows = [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]
    for r in rows:
        r["created_at"] = r["created_at"].isoformat()
    return rows


def _payload(f: dict, hits: list[dict]) -> dict:
    return {
        "filter": f["name"],
        "count": len(hits),
        "claims": [{"id": h["id"], "headline": h["headline"], "category": h["category"],
                    "horizon": h["horizon"], "confidence": h["confidence"],
                    "affected": h["affected"], "source": h["source"], "url": h["url"],
                    "made_at": h["created_at"]} for h in hits[:ALERT_BATCH]],
        "note": "Interpretations, not advice. Each one is scored in the Ledger once its horizon "
                "elapses, whichever way it goes.",
    }


def _send_webhook(url: str, payload: dict) -> bool:
    """POST the payload. Re-checked at send time, not just at save time — DNS can change between
    the two, which is the whole point of a rebinding attack. Redirects are refused for the same
    reason: a 302 to 169.254.169.254 would walk straight past the check that just passed."""
    ok, why = webhook_target_ok(url)
    if not ok:
        log.warning("refusing webhook delivery: %s", why)
        return False
    try:
        r = httpx.post(url, json=payload, timeout=10, follow_redirects=False,
                       headers={"User-Agent": "Rhumb-Alerts/1.0"})
        return r.status_code < 400
    except Exception as exc:
        log.warning("webhook delivery failed (%s)", type(exc).__name__)
        return False


def deliver_due(conn: psycopg.Connection, now_limit: int = 50) -> dict:
    """Send every subscription whose throttle has elapsed and that has something new to say.

    Nothing is sent when a filter matched nothing — an alert that says "no news" is the noise the
    brief's "throttled hard" exists to prevent. The high-water mark still advances, so the next run
    does not re-examine the same claims.
    """
    from . import mail

    with conn.cursor() as cur:
        cur.execute(
            sql.SQL("""SELECT {cols}, user_id, last_claim_id,
                              (SELECT email FROM users u WHERE u.id = radar_filters.user_id)
                         FROM radar_filters
                        WHERE subscribed
                          AND (last_sent_at IS NULL
                               OR last_sent_at <= now() - make_interval(mins => throttle_mins))
                     ORDER BY last_sent_at NULLS FIRST LIMIT %s""").format(cols=_COLS),
            (now_limit,))
        rows = cur.fetchall()

    sent, examined, retained = 0, 0, 0
    for r in rows:
        f, since, email = _row(r), r[9], r[10]
        # The high-water mark is a claim id, not a timestamp: ids are monotonic and a timestamp
        # comparison would resend anything written during the same second as the last run.
        with conn.cursor() as cur:
            fresh = _claims_since(cur, since)

        examined += len(fresh)
        spec = normalise_spec(f["spec"])
        hits = [c for c in fresh if matches(c, spec)]
        high_water = max((c["id"] for c in fresh), default=since)

        delivered = True          # nothing to send counts as delivered — see the note below
        if hits and email:
            payload = _payload(f, hits)
            if f["channel"] == "webhook":
                delivered = _send_webhook(f["webhook_url"], payload)
            else:
                body = "\n".join(
                    f"- {c['headline']} ({c['category']}, over {c['horizon']}, "
                    f"{round((c['confidence'] or 0) * 100)}% confidence)\n  {c['url'] or ''}"
                    for c in payload["claims"])
                delivered = mail.send(
                    email, f"Rhumb — {len(hits)} new on “{f['name']}”",
                    f"{len(hits)} interpretations matched your saved filter “{f['name']}”.\n\n"
                    f"{body}\n\n{payload['note']}\n")
            sent += 1 if delivered else 0

        # The mark advances only when the batch actually went out. A failed send that still moved
        # the mark would drop those claims permanently — the reader would never hear about them and
        # nothing would record that they were missed. Holding it means a transient outage retries on
        # the next tick, and a permanently broken endpoint retries no faster than its own throttle,
        # so this cannot become a hot loop. `last_sent_at` moves either way, which is what bounds it.
        with conn.cursor() as cur:
            if delivered:
                cur.execute("UPDATE radar_filters SET last_sent_at=now(), last_claim_id=%s "
                            "WHERE id=%s", (high_water, f["id"]))
            else:
                retained += 1
                cur.execute("UPDATE radar_filters SET last_sent_at=now() WHERE id=%s", (f["id"],))
        conn.commit()

    return {"subscriptions": len(rows), "claims_examined": examined, "delivered": sent,
            "retried_next_tick": retained}


def preview(conn: psycopg.Connection, spec: dict, hours: int = 336, limit: int = 60) -> dict:
    """How many of the recent claims this spec would have caught — shown while editing, so a filter
    that matches nothing is visible before it is saved rather than after a week of silence."""
    spec = normalise_spec(spec)
    with conn.cursor() as cur:
        cur.execute(
            """SELECT c.id, c.created_at, c.affected, c.horizon, c.confidence, c.cluster_id,
                      e.title, e.source, e.geo, e.category
                 FROM claims c LEFT JOIN events e ON e.id = c.event_id
                WHERE c.created_at >= now() - make_interval(hours => %s)
             ORDER BY c.created_at DESC LIMIT 500""", (hours,))
        cols = ("id", "created_at", "affected", "horizon", "confidence", "cluster_id",
                "headline", "source", "geo", "category")
        rows = [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]
    hits = [r for r in rows if matches(r, spec)]
    for h in hits:
        h["created_at"] = h["created_at"].isoformat()
    return {"considered": len(rows), "matched": len(hits), "spec": spec,
            "sample": [{"id": h["id"], "headline": h["headline"], "category": h["category"],
                        "horizon": h["horizon"], "confidence": h["confidence"]}
                       for h in hits[:limit]]}


def as_json(obj) -> str:
    return json.dumps(obj, default=str)
