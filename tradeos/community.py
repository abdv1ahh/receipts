"""Community & social graph (Slice F): a feed of public trades, follows between traders, reactions,
comments, an honest trader leaderboard, and lightweight report/auto-hide moderation.

The focus stays on learning, not vanity: a public trade keeps its 'not advice' framing, the
leaderboard ranks by an HONEST win rate above a real sample floor — never a single raw-return number
that would invite fabrication or pumping — and public UGC is length-capped, React-escaped, object-level
authorized, and report/auto-hideable so the surface can't be turned into a pump instrument.

Pure helpers first (handle validation, leaderboard ranking), then the DB layer.
"""
from __future__ import annotations

import re

import psycopg

from . import trades

HANDLE_RE = re.compile(r"^[a-z0-9_]{3,20}$")
RESERVED = {"admin", "tradeos", "root", "support", "api", "moderator", "mod", "system", "official",
            "staff", "help", "about", "settings", "me", "null", "undefined"}
LEADERBOARD_MIN_CLOSED = 10       # a trader is ranked only above a real sample (matches perf honesty)
REPORTS_TO_HIDE = 3               # distinct reports auto-hide, pending admin review (Slice K)


def normalize_handle(raw):
    """Lowercased, @-stripped handle if it is 3–20 chars of [a-z0-9_] and not reserved, else None."""
    if not raw:
        return None
    h = raw.strip().lstrip("@").lower()
    return h if HANDLE_RE.match(h) and h not in RESERVED else None


def trader_leaderboard(rows):
    """rows: [{handle, summary}] where summary is `trades.summarize_performance` over a trader's PUBLIC
    closed trades. Only sufficiently-sampled traders are ranked, by win rate then sample size — never by
    a raw return figure. Returns ranked dicts."""
    ranked = [{"handle": r["handle"], "n_closed": r["summary"]["n_closed"],
               "win_rate": r["summary"]["win_rate"], "avg_reward_risk": r["summary"].get("avg_reward_risk")}
              for r in rows if r["summary"].get("sufficient")]
    ranked.sort(key=lambda x: (x["win_rate"], x["n_closed"]), reverse=True)
    return ranked


# ------------------------------------------------------------------ DB: profiles

def _public_perf(cur, user_id):
    cur.execute("SELECT direction, status, entry_price, exit_price, stop_price, target_price, strategy "
                "FROM trades WHERE user_id=%s AND is_public AND hidden=false", (user_id,))
    rows = [{"strategy": s, "rr": trades.reward_risk(e, st, tg, d),
             "realized_pnl_pct": trades.realized_pnl_pct(e, ex, d) if status == "closed" else None}
            for d, status, e, ex, st, tg, s in cur.fetchall()]
    return trades.summarize_performance(rows)


def set_profile(conn: psycopg.Connection, user_id, handle=None, bio=None):
    with conn.cursor() as cur:
        if handle is not None:
            h = normalize_handle(handle)
            if not h:
                return {"error": "Handle must be 3–20 characters: lowercase letters, numbers, underscore."}
            cur.execute("SELECT 1 FROM users WHERE handle=%s AND id<>%s", (h, user_id))
            if cur.fetchone():
                return {"error": "That handle is taken."}
            cur.execute("UPDATE users SET handle=%s WHERE id=%s", (h, user_id))
        if bio is not None:
            cur.execute("UPDATE users SET bio=%s WHERE id=%s", ((bio.strip()[:280] or None), user_id))
        conn.commit()
        cur.execute("SELECT handle, bio FROM users WHERE id=%s", (user_id,))
        hr, br = cur.fetchone()
    return {"ok": True, "handle": hr, "bio": br}


def public_profile(conn: psycopg.Connection, handle, viewer_id=None):
    with conn.cursor() as cur:
        cur.execute("SELECT id, handle, bio, created_at FROM users WHERE handle=%s", (handle,))
        u = cur.fetchone()
        if not u:
            return {"found": False}
        uid = u[0]
        perf = _public_perf(cur, uid)
        cur.execute("SELECT count(*) FROM user_follows WHERE followee_id=%s", (uid,))
        followers = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM user_follows WHERE follower_id=%s", (uid,))
        following = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM trades WHERE user_id=%s AND is_public AND hidden=false", (uid,))
        public_trades = cur.fetchone()[0]
        is_following = False
        if viewer_id and viewer_id != uid:
            cur.execute("SELECT 1 FROM user_follows WHERE follower_id=%s AND followee_id=%s", (viewer_id, uid))
            is_following = cur.fetchone() is not None
    return {"found": True, "id": uid, "handle": u[1], "bio": u[2], "joined": u[3].isoformat()[:10],
            "followers": followers, "following": following, "public_trades": public_trades,
            "performance": perf, "is_following": is_following, "is_me": viewer_id == uid}


def follow_user(conn: psycopg.Connection, follower_id, handle):
    with conn.cursor() as cur:
        cur.execute("SELECT id, handle FROM users WHERE handle=%s", (handle,))
        u = cur.fetchone()
        if not u:
            return {"error": "No such trader."}
        if u[0] == follower_id:
            return {"error": "You can't follow yourself."}
        cur.execute("INSERT INTO user_follows (follower_id, followee_id) VALUES (%s,%s) "
                    "ON CONFLICT DO NOTHING", (follower_id, u[0]))
        conn.commit()
    return {"following": True, "handle": u[1]}


def unfollow_user(conn: psycopg.Connection, follower_id, handle):
    with conn.cursor() as cur:
        cur.execute("DELETE FROM user_follows WHERE follower_id=%s "
                    "AND followee_id=(SELECT id FROM users WHERE handle=%s)", (follower_id, handle))
        conn.commit()
    return {"following": False}


# ------------------------------------------------------------------ DB: feed

def public_feed(conn: psycopg.Connection, viewer_id=None, scope="public", before_id=None, limit=30):
    limit = max(1, min(50, limit))
    conds = ["t.is_public", "t.hidden = false"]
    args: list = []
    if scope == "following":
        if not viewer_id:
            return []
        conds.append("t.user_id IN (SELECT followee_id FROM user_follows WHERE follower_id=%s)")
        args.append(viewer_id)
    if before_id:
        conds.append("t.id < %s")
        args.append(before_id)
    with conn.cursor() as cur:
        cur.execute(
            f"""SELECT t.id, t.symbol, t.direction, t.status, t.entry_price, t.exit_price, t.stop_price,
                       t.target_price, t.strategy, t.asset_class, t.image_path, t.created_at, u.handle,
                   COALESCE((SELECT count(*) FROM trade_reactions r WHERE r.trade_id=t.id AND r.kind='like'),0),
                   COALESCE((SELECT count(*) FROM trade_comments c WHERE c.trade_id=t.id AND NOT c.hidden),0)
                FROM trades t JOIN users u ON u.id=t.user_id
                WHERE {' AND '.join(conds)} ORDER BY t.id DESC LIMIT %s""", (*args, limit))
        rows = cur.fetchall()
    out = []
    for (tid, sym, d, status, entry, exit_, stop, target, strat, asset, img, created, handle, likes, comments) in rows:
        out.append({"id": tid, "symbol": sym, "direction": d, "status": status, "entry_price": entry,
                    "reward_risk": trades.reward_risk(entry, stop, target, d),
                    "realized_pnl_pct": trades.realized_pnl_pct(entry, exit_, d) if status == "closed" else None,
                    "strategy": strat, "asset_class": asset, "has_image": bool(img),
                    "created_at": created.isoformat(), "author": handle or "trader",
                    "likes": likes, "comments": comments})
    return out


# ------------------------------------------------------------------ DB: reactions, comments, reports

def _visible_trade(cur, trade_id, viewer_id):
    """Return (is_public, hidden, owner_id) or None; a private trade is visible only to its owner."""
    cur.execute("SELECT is_public, hidden, user_id FROM trades WHERE id=%s", (trade_id,))
    t = cur.fetchone()
    if not t or (not t[0] and t[2] != viewer_id):
        return None
    return t


def react(conn: psycopg.Connection, user_id, trade_id, kind):
    if kind not in ("like", "save"):
        return {"error": "invalid reaction"}
    with conn.cursor() as cur:
        t = _visible_trade(cur, trade_id, user_id)
        if not t or t[1]:                      # missing/private/hidden
            return {"error": "not found"}
        cur.execute("INSERT INTO trade_reactions (trade_id, user_id, kind) VALUES (%s,%s,%s) "
                    "ON CONFLICT (trade_id, user_id, kind) DO NOTHING", (trade_id, user_id, kind))
        conn.commit()
    return {"ok": True, "kind": kind}


def unreact(conn: psycopg.Connection, user_id, trade_id, kind):
    with conn.cursor() as cur:
        cur.execute("DELETE FROM trade_reactions WHERE trade_id=%s AND user_id=%s AND kind=%s",
                    (trade_id, user_id, kind))
        conn.commit()
    return {"ok": True}


def my_reactions(conn: psycopg.Connection, user_id, trade_id):
    with conn.cursor() as cur:
        cur.execute("SELECT kind FROM trade_reactions WHERE trade_id=%s AND user_id=%s", (trade_id, user_id))
        return {r[0] for r in cur.fetchall()}


def saved_trades(conn: psycopg.Connection, user_id):
    with conn.cursor() as cur:
        cur.execute("SELECT trade_id FROM trade_reactions WHERE user_id=%s AND kind='save' ORDER BY created_at DESC",
                    (user_id,))
        return [r[0] for r in cur.fetchall()]


def list_comments(conn: psycopg.Connection, trade_id, viewer_id=None):
    with conn.cursor() as cur:
        if not _visible_trade(cur, trade_id, viewer_id):
            return {"found": False, "comments": []}
        cur.execute("""SELECT c.id, c.body, c.created_at, u.handle, c.user_id
                       FROM trade_comments c JOIN users u ON u.id=c.user_id
                       WHERE c.trade_id=%s AND NOT c.hidden ORDER BY c.created_at""", (trade_id,))
        items = [{"id": i, "body": b, "created_at": ca.isoformat(), "author": h or "trader",
                  "mine": viewer_id == uid} for i, b, ca, h, uid in cur.fetchall()]
    return {"found": True, "comments": items}


def add_comment(conn: psycopg.Connection, user_id, trade_id, body):
    body = (body or "").strip()[:1000]
    if not body:
        return {"error": "empty comment"}
    with conn.cursor() as cur:
        t = _visible_trade(cur, trade_id, user_id)
        if not t or not t[0] or t[1]:          # must be public + not hidden
            return {"error": "cannot comment on this trade"}
        cur.execute("INSERT INTO trade_comments (trade_id, user_id, body) VALUES (%s,%s,%s) RETURNING id",
                    (trade_id, user_id, body))
        cid = cur.fetchone()[0]
        conn.commit()
    return {"ok": True, "id": cid}


def delete_comment(conn: psycopg.Connection, user_id, comment_id, is_admin=False):
    with conn.cursor() as cur:
        cur.execute("SELECT c.user_id, t.user_id FROM trade_comments c JOIN trades t ON t.id=c.trade_id "
                    "WHERE c.id=%s", (comment_id,))
        r = cur.fetchone()
        if not r:
            return {"error": "not found"}
        if not (is_admin or user_id == r[0] or user_id == r[1]):   # author, trade owner, or admin
            return {"error": "not allowed"}
        cur.execute("DELETE FROM trade_comments WHERE id=%s", (comment_id,))
        conn.commit()
    return {"ok": True}


def report(conn: psycopg.Connection, reporter_id, target_type, target_id, reason):
    if target_type not in ("trade", "comment"):
        return {"error": "invalid target"}
    with conn.cursor() as cur:
        cur.execute("INSERT INTO content_reports (reporter_id, target_type, target_id, reason) "
                    "VALUES (%s,%s,%s,%s) ON CONFLICT (reporter_id, target_type, target_id) DO NOTHING",
                    (reporter_id, target_type, target_id, (reason or "").strip()[:280] or None))
        cur.execute("SELECT count(*) FROM content_reports WHERE target_type=%s AND target_id=%s "
                    "AND resolved_at IS NULL", (target_type, target_id))
        n = cur.fetchone()[0]
        hidden = n >= REPORTS_TO_HIDE
        if hidden:                              # auto-hide pending review (Slice K console)
            tbl = "trades" if target_type == "trade" else "trade_comments"
            cur.execute(f"UPDATE {tbl} SET hidden=true WHERE id=%s", (target_id,))
        conn.commit()
    return {"ok": True, "reports": n, "hidden": hidden}


# ------------------------------------------------------------------ DB: leaderboard

def trader_leaderboard_data(conn: psycopg.Connection, limit=25):
    with conn.cursor() as cur:
        cur.execute("SELECT id, handle FROM users WHERE handle IS NOT NULL")
        users = cur.fetchall()
        rows = [{"handle": handle, "summary": _public_perf(cur, uid)} for uid, handle in users]
    return trader_leaderboard(rows)[:limit]
