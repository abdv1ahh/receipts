"""Admin dashboard (Slice K): moderation, user/tier management, and an audit viewer.

Everything here consumes REAL platform state — the Slice F content_reports + auto-hide, the users
table, the append-only audit_log — and every mutation is written to that same audit_log via
authn.audit, so an admin action is itself an auditable record. Pure validation helpers come first
(self-safety guardrails, allowed actions) so they can be unit-tested offline; the DB layer follows.

Deliberate safety choices:
  * Tier changes are limited to free/retail/pro. Granting 'admin' is refused here — admin requires a
    TOTP secret (authn.login won't let an admin without MFA in), so it is provisioned via the CLI,
    never a web click that could lock someone out or hand out privilege.
  * You cannot change your own tier or ban yourself (no self-lockout), and admins cannot be banned or
    retiered from the console.
  * A ban is enforced server-side: the account's sessions are dropped, its public trades are hidden,
    and authn refuses future logins/sessions. It is fully reversible (unban), but hidden content is
    left for the moderator to restore deliberately via the queue.
"""
from __future__ import annotations

import psycopg
from psycopg import sql

from . import authn

TIER_TARGETS = ("free", "retail", "pro")     # 'admin' is CLI-only (needs TOTP) — never a web grant
RESOLUTIONS = ("hide", "unhide", "dismiss")


# ------------------------------------------------------------------ pure guardrails

def validate_tier_change(actor_id: int, target_id: int, tier: str) -> tuple[bool, str | None]:
    if actor_id == target_id:
        return False, "You can't change your own tier."
    if tier not in TIER_TARGETS:
        return False, "Tier must be free, retail or pro (admin is provisioned via the CLI with TOTP)."
    return True, None


def can_ban(actor_id: int, target_id: int) -> tuple[bool, str | None]:
    if actor_id == target_id:
        return False, "You can't ban yourself."
    return True, None


def resolution_ok(action: str) -> bool:
    return action in RESOLUTIONS


def _like(term: str) -> str:
    """Escape LIKE wildcards so a stray % / _ in a search term can't match everything."""
    return "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_").strip() + "%"


# ------------------------------------------------------------------ overview

def overview(conn: psycopg.Connection) -> dict:
    with conn.cursor() as cur:
        cur.execute("SELECT tier, count(*) FROM users GROUP BY tier")
        by_tier = dict(cur.fetchall())
        cur.execute("SELECT count(*) FROM users WHERE banned")
        banned = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM trades")
        trades_total = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM trades WHERE is_public AND NOT hidden")
        trades_public = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM trades WHERE hidden")
        trades_hidden = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM trade_comments WHERE hidden")
        comments_hidden = cur.fetchone()[0]
        cur.execute("SELECT count(DISTINCT (target_type, target_id)) FROM content_reports "
                    "WHERE resolved_at IS NULL")
        open_reports = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM audit_log")
        audit_rows = cur.fetchone()[0]
    return {
        "users": {"total": sum(by_tier.values()), "by_tier": by_tier, "banned": banned},
        "trades": {"total": trades_total, "public": trades_public, "hidden": trades_hidden},
        "comments": {"hidden": comments_hidden},
        "moderation": {"open_reports": open_reports},
        "audit_rows": audit_rows,
    }


# ------------------------------------------------------------------ moderation queue

def _target_preview(cur, target_type: str, target_id: int) -> dict | None:
    if target_type == "trade":
        cur.execute("SELECT t.symbol, t.direction, t.status, t.hidden, u.handle "
                    "FROM trades t JOIN users u ON u.id=t.user_id WHERE t.id=%s", (target_id,))
        r = cur.fetchone()
        if not r:
            return None
        return {"hidden": r[3], "author": r[4] or "trader",
                "content": f"{(r[0] or '—')} {r[1]} · {r[2]}"}
    cur.execute("SELECT c.body, c.hidden, u.handle FROM trade_comments c JOIN users u ON u.id=c.user_id "
                "WHERE c.id=%s", (target_id,))
    r = cur.fetchone()
    if not r:
        return None
    return {"hidden": r[1], "author": r[2] or "trader", "content": (r[0] or "")[:200]}


def moderation_queue(conn: psycopg.Connection, limit: int = 50) -> list[dict]:
    limit = max(1, min(100, limit))
    with conn.cursor() as cur:
        cur.execute(
            """SELECT target_type, target_id, count(*) AS n, max(created_at) AS last_at,
                      array_agg(DISTINCT reason) FILTER (WHERE reason IS NOT NULL) AS reasons
               FROM content_reports WHERE resolved_at IS NULL
               GROUP BY target_type, target_id ORDER BY n DESC, last_at DESC LIMIT %s""", (limit,))
        groups = cur.fetchall()
        out = []
        for target_type, target_id, n, last_at, reasons in groups:
            preview = _target_preview(cur, target_type, target_id)
            if preview is None:                # target was deleted after being reported — skip
                continue
            out.append({"target_type": target_type, "target_id": target_id, "reports": n,
                        "last_reported": last_at.isoformat(), "reasons": list(reasons or []),
                        **preview})
    return out


def resolve(conn: psycopg.Connection, actor: dict, target_type: str, target_id: int, action: str) -> dict:
    if not resolution_ok(action):
        return {"error": "invalid action"}
    if target_type not in ("trade", "comment"):
        return {"error": "invalid target"}
    # Identifier() rather than an f-string. `target_type` is already checked against a two-value
    # allowlist above, so this was never injectable — but the check and the interpolation are eight
    # lines apart, and that gap is where this class of bug actually lives. Composed, the guarantee
    # survives someone moving the check.
    tbl = sql.Identifier("trades" if target_type == "trade" else "trade_comments")
    with conn.cursor() as cur:
        cur.execute(sql.SQL("SELECT 1 FROM {} WHERE id=%s").format(tbl), (target_id,))
        if not cur.fetchone():
            return {"error": "not found"}
        if action in ("hide", "unhide"):
            cur.execute(sql.SQL("UPDATE {} SET hidden=%s WHERE id=%s").format(tbl),
                        (action == "hide", target_id))
        cur.execute("UPDATE content_reports SET resolved_at=now(), resolved_by=%s, resolution=%s "
                    "WHERE target_type=%s AND target_id=%s AND resolved_at IS NULL",
                    (actor["email"], action, target_type, target_id))
        resolved = cur.rowcount
        conn.commit()
    authn.audit(conn, actor["email"], "mod_resolve", f"{target_type}:{target_id}",
                {"action": action, "reports_resolved": resolved})
    return {"ok": True, "action": action, "reports_resolved": resolved}


# ------------------------------------------------------------------ user / tier management

def list_users(conn: psycopg.Connection, q: str = "", limit: int = 50) -> list[dict]:
    limit = max(1, min(200, limit))
    q = (q or "").strip()[:64]
    where, args = sql.SQL(""), []
    if q:
        where = sql.SQL("WHERE u.email ILIKE %s ESCAPE '\\' OR u.handle ILIKE %s ESCAPE '\\'")
        args = [_like(q), _like(q)]
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL("""SELECT u.id, u.email, u.handle, u.tier, u.banned, u.created_at,
                       (SELECT count(*) FROM trades t WHERE t.user_id=u.id) AS trades,
                       (SELECT count(*) FROM content_reports r WHERE r.resolved_at IS NULL AND
                          ((r.target_type='trade'   AND r.target_id IN (SELECT id FROM trades         WHERE user_id=u.id))
                        OR (r.target_type='comment' AND r.target_id IN (SELECT id FROM trade_comments WHERE user_id=u.id)))
                       ) AS open_reports
                FROM users u {where} ORDER BY u.created_at DESC LIMIT %s""").format(where=where),
            (*args, limit))
        rows = cur.fetchall()
    return [{"id": r[0], "email": r[1], "handle": r[2], "tier": r[3], "banned": r[4],
             "joined": r[5].isoformat()[:10], "trades": r[6], "open_reports": r[7]} for r in rows]


def set_tier(conn: psycopg.Connection, actor: dict, user_id: int, tier: str) -> dict:
    ok, err = validate_tier_change(actor["id"], user_id, tier)
    if not ok:
        return {"error": err}
    with conn.cursor() as cur:
        cur.execute("SELECT tier FROM users WHERE id=%s", (user_id,))
        row = cur.fetchone()
        if not row:
            return {"error": "user not found"}
        if row[0] == "admin":
            return {"error": "admin accounts are managed via the CLI."}
        cur.execute("UPDATE users SET tier=%s WHERE id=%s", (tier, user_id))
        conn.commit()
    authn.audit(conn, actor["email"], "admin_set_tier", str(user_id), {"from": row[0], "to": tier})
    return {"ok": True, "tier": tier}


def set_banned(conn: psycopg.Connection, actor: dict, user_id: int, banned: bool) -> dict:
    ok, err = can_ban(actor["id"], user_id)
    if not ok:
        return {"error": err}
    with conn.cursor() as cur:
        cur.execute("SELECT tier FROM users WHERE id=%s", (user_id,))
        row = cur.fetchone()
        if not row:
            return {"error": "user not found"}
        if row[0] == "admin":
            return {"error": "cannot ban an admin account."}
        cur.execute("UPDATE users SET banned=%s WHERE id=%s", (banned, user_id))
        if banned:                              # drop live sessions + hide their public trades
            cur.execute("DELETE FROM sessions WHERE user_id=%s", (user_id,))
            cur.execute("UPDATE trades SET hidden=true WHERE user_id=%s AND is_public", (user_id,))
        conn.commit()
    authn.audit(conn, actor["email"], "admin_ban" if banned else "admin_unban", str(user_id))
    return {"ok": True, "banned": banned}


# ------------------------------------------------------------------ audit viewer

def audit_tail(conn: psycopg.Connection, limit: int = 100, action: str | None = None) -> list[dict]:
    """Read the append-only audit_log, newest first, optionally filtered by action. Read-only — the
    table has a DELETE/UPDATE-forbidding trigger, so this can only ever observe."""
    limit = max(1, min(500, limit))
    where, args = sql.SQL(""), []
    if action:
        where = sql.SQL("WHERE action=%s")
        args = [action.strip()[:64]]
    with conn.cursor() as cur:
        cur.execute(sql.SQL("SELECT id, actor, action, object, at, detail FROM audit_log {where} "
                            "ORDER BY id DESC LIMIT %s").format(where=where), (*args, limit))
        rows = cur.fetchall()
    return [{"id": r[0], "actor": r[1], "action": r[2], "object": r[3],
             "at": r[4].isoformat(), "detail": r[5]} for r in rows]


def audit_actions(conn: psycopg.Connection) -> list[str]:
    """Distinct action names, for the viewer's filter dropdown."""
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT action FROM audit_log ORDER BY action")
        return [r[0] for r in cur.fetchall()]
