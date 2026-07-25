"""Unified search (Slice J) across the whole product: assets/issuers, institutions, insiders, the
intelligence library, and public traders. Read-only. Only PUBLIC handles are searchable (never
emails or user ids); issuer/institution/insider entities are public SEC records. User wildcards are
escaped so a stray '%' can't turn into a match-all.
"""
from __future__ import annotations

import psycopg


def clean_query(q):
    """Trim, cap length, and escape LIKE wildcards (so '%' / '_' are literal, not match-all)."""
    q = (q or "").strip()[:64]
    return q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search(conn: psycopg.Connection, q, limit=6) -> dict:
    ql = clean_query(q)
    empty = {"symbols": [], "institutions": [], "insiders": [], "library": [], "traders": []}
    if len(ql) < 1:
        return empty
    like, pre = f"%{ql}%", f"{ql}%"
    out: dict = {}
    _issuer = ("FROM security_map m JOIN entities e ON e.id=m.entity_id "
               "WHERE e.kind='issuer' AND m.source='sec_company_tickers'")
    with conn.cursor() as cur:
        # symbol-prefix matches first (NV -> NVDA), shortest ticker first; then fill with name matches
        cur.execute(f"SELECT DISTINCT ON (m.symbol) m.symbol, e.name, m.entity_id {_issuer} "
                    f"AND m.symbol ILIKE %s ORDER BY m.symbol LIMIT %s", (pre, limit * 3))
        pref = sorted(cur.fetchall(), key=lambda r: (len(r[0]), r[0]))
        seen, syms = set(), []
        for s, n, e in pref:
            if s not in seen and len(syms) < limit:
                seen.add(s)
                syms.append({"symbol": s, "name": n, "entity_id": e})
        if len(syms) < limit:
            cur.execute(f"SELECT DISTINCT ON (m.symbol) m.symbol, e.name, m.entity_id {_issuer} "
                        f"AND e.name ILIKE %s ORDER BY m.symbol LIMIT %s", (like, limit))
            for s, n, e in cur.fetchall():
                if s not in seen and len(syms) < limit:
                    seen.add(s)
                syms.append({"symbol": s, "name": n, "entity_id": e})
        out["symbols"] = syms
        cur.execute("SELECT id, name FROM entities WHERE kind='institution' AND name ILIKE %s "
                    "ORDER BY name LIMIT %s", (like, limit))
        out["institutions"] = [{"entity_id": i, "name": n} for i, n in cur.fetchall()]
        cur.execute("SELECT cik, name FROM entities WHERE kind='insider' AND name ILIKE %s "
                    "ORDER BY name LIMIT %s", (like, limit))
        out["insiders"] = [{"cik": c, "name": n} for c, n in cur.fetchall()]
        cur.execute("SELECT slug, title FROM library_entries WHERE title ILIKE %s ORDER BY title LIMIT %s",
                    (like, limit))
        out["library"] = [{"slug": s, "title": t} for s, t in cur.fetchall()]
        cur.execute("SELECT handle, bio FROM users WHERE handle IS NOT NULL AND handle ILIKE %s "
                    "ORDER BY handle LIMIT %s", (like, limit))
        out["traders"] = [{"handle": h, "bio": b} for h, b in cur.fetchall()]
    return out
