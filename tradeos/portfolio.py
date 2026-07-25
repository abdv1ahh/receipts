"""Paper portfolios: shadow the smart money, tracked honestly against SPY (Slice C).

Positions are paper only. Every figure is computed from real prices_eod over the actual holding
window versus SPY over the same window; a symbol we cannot price is reported as `priced: False`
(pending), never filled with a guessed value. Entry follows the backtest's spirit: the first
trading day on/after the paper entry date. This is the live-building public track record.
"""
from __future__ import annotations

from datetime import date

import psycopg

from .backtest.engine import Series, _first_ge

BENCHMARK = "SPY"


# ------------------------------------------------------------------ pure P&L

def position_pnl(sym: Series, spy: Series, opened_on: date) -> dict:
    """Return vs SPY for one paper position from its entry to the latest priced day, or
    {priced: False} when the pair cannot be resolved (no price history / not enough window)."""
    entry = _first_ge(sym.days, opened_on)
    last = sym.last_day
    if entry is None or entry not in spy.close or last is None or last not in spy.close or last <= entry:
        return {"priced": False}
    sr = sym.close[last] / sym.close[entry] - 1.0
    br = spy.close[last] / spy.close[entry] - 1.0
    return {"priced": True, "entry_day": entry.isoformat(), "entry_price": round(sym.close[entry], 4),
            "current_day": last.isoformat(), "current_price": round(sym.close[last], 4),
            "return": round(sr, 6), "spy_return": round(br, 6), "excess": round(sr - br, 6),
            "days_held": (last - entry).days}


def summarize(positions: list[dict]) -> dict:
    """Equal-weight portfolio summary over the priced positions only. Pending names are counted
    and excluded from the averages (honesty: we do not average in a zero for an unpriced name)."""
    priced = [p for p in positions if p.get("priced")]
    n = len(priced)
    avg_ret = sum(p["return"] for p in priced) / n if n else None
    avg_spy = sum(p["spy_return"] for p in priced) / n if n else None
    return {
        "positions": len(positions), "priced": n, "pending": len(positions) - n,
        "avg_return": round(avg_ret, 6) if n else None,
        "spy_return": round(avg_spy, 6) if n else None,
        "avg_excess": round(avg_ret - avg_spy, 6) if n else None,
        "beat_spy": sum(1 for p in priced if p["excess"] > 0),
    }


# ------------------------------------------------------------------ DB helpers

def _series(conn: psycopg.Connection, symbol: str) -> Series:
    with conn.cursor() as cur:
        cur.execute("SELECT day, close FROM prices_eod WHERE symbol=%s ORDER BY day", (symbol,))
        return Series.from_rows(cur.fetchall())


def detail(conn: psycopg.Connection, portfolio_id: int, user_id: int) -> dict:
    """Full portfolio with live P&L. Scoped to user_id (object-level authorization)."""
    with conn.cursor() as cur:
        cur.execute("SELECT id, name, kind, created_at FROM portfolios WHERE id=%s AND user_id=%s",
                    (portfolio_id, user_id))
        p = cur.fetchone()
        if not p:
            return {"found": False}
        cur.execute("SELECT id, symbol, entity_id, opened_on, note FROM portfolio_positions "
                    "WHERE portfolio_id=%s ORDER BY opened_on DESC", (portfolio_id,))
        rows = cur.fetchall()
    from . import news  # local import avoids any module-load cycle
    sig = news.signal_symbols(conn)   # cross-plane: which positions still show a smart-money signal
    spy = _series(conn, BENCHMARK)
    positions = []
    for pid, sym, ent, opened, note in rows:
        pnl = position_pnl(_series(conn, sym), spy, opened)
        positions.append({"id": pid, "symbol": sym, "entity_id": ent, "has_signal": sym in sig,
                          "opened_on": opened.isoformat(), "note": note, **pnl})
    summary = summarize(positions)
    summary["signal_count"] = sum(1 for p in positions if p["has_signal"])
    return {"found": True, "id": p[0], "name": p[1], "kind": p[2], "created_at": p[3].isoformat(),
            "summary": summary, "positions": positions}


def list_for_user(conn: psycopg.Connection, user_id: int) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM portfolios WHERE user_id=%s ORDER BY created_at DESC", (user_id,))
        ids = [r[0] for r in cur.fetchall()]
    out = []
    for pid in ids:
        d = detail(conn, pid, user_id)
        out.append({"id": d["id"], "name": d["name"], "kind": d["kind"], "summary": d["summary"]})
    return out


def populate_shadow(conn: psycopg.Connection, portfolio_id: int, buckets: list[str], limit: int = 20) -> int:
    """Open one paper position per issuer that converged at the given bucket(s), entered at that
    issuer's earliest such cluster, keeping only names we can actually price. Gives an instant,
    honest, forward-looking track record from historical signals."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT q.issuer_entity, q.opened, q.sym FROM (
                   SELECT DISTINCT ON (c.issuer_entity) c.issuer_entity, c.as_of::date AS opened,
                          (SELECT symbol FROM security_map m WHERE m.entity_id=c.issuer_entity
                             AND m.source='sec_company_tickers' ORDER BY confidence DESC LIMIT 1) AS sym
                   FROM signal_clusters c WHERE c.confidence_bucket = ANY(%s)
                   ORDER BY c.issuer_entity, c.as_of ASC
               ) q WHERE q.sym IS NOT NULL ORDER BY q.opened DESC""",
            (buckets,),
        )
        cand = cur.fetchall()
    added = 0
    with conn.cursor() as cur:
        for ent, opened, sym in cand:
            cur.execute("SELECT min(day), max(day) FROM prices_eod WHERE symbol=%s AND day >= %s", (sym, opened))
            lo, hi = cur.fetchone()
            if lo is None or hi is None or hi <= lo:
                continue  # cannot price this shadow -> skip rather than invent a return
            cur.execute(
                "INSERT INTO portfolio_positions (portfolio_id, symbol, entity_id, opened_on, note) "
                "VALUES (%s,%s,%s,%s,%s) ON CONFLICT (portfolio_id, symbol) DO NOTHING",
                (portfolio_id, sym, ent, opened, f"shadowed {'/'.join(buckets)} convergence"),
            )
            added += cur.rowcount
            if added >= limit:
                break
    conn.commit()
    return added
