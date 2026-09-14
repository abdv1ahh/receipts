"""Job 2 STEP 3 — does the convergence signal have a demonstrable edge?

Read-only. Computes every statistic with the engine's own `excess_return`, the ledger's `mean_ci`
for MEANS and `wilson_interval` for PROPORTIONS. Those two are not interchangeable: a Wilson
interval is a statement about a proportion and applying it to a mean excess return would be a
category error, so hit rate gets Wilson and mean excess gets the t-style interval built for it.

Episodes are grouped by (issuer, VERSION). `run_backtest` groups by issuer ALONE, which merges a
v3 and a v4 cluster within EPISODE_GAP_DAYS into one episode and attributes it to whichever fired
first — 146 of its 595 episodes span both versions, and it credits v4 with only 12. That grouping
cannot answer "split by version, never pooled", so the per-version numbers here are recomputed
rather than read out of signal_outcomes.
"""
from __future__ import annotations

import json
from collections import defaultdict

from tradeos import db
from tradeos.backtest.engine import HORIZONS, excess_return, group_episodes, wilson_interval
from tradeos.backtest.run import load_series
from tradeos.ledger import mean_ci

MIN_N = 30          # below this a percentage is not reported, per the brief


def stats(vals: list[float]) -> dict:
    """Mean excess + its interval, and hit rate + its Wilson interval. Never a bare point rate."""
    n = len(vals)
    if n == 0:
        return {"n": 0, "insufficient": True}
    hits = sum(1 for v in vals if v > 0)
    m = mean_ci(vals)
    w = wilson_interval(hits, n)
    out = {
        "n": n,
        "mean_excess": m["mean"], "mean_lo": m["lo"], "mean_hi": m["hi"],
        "mean_excludes_zero": m["significant"],
        "hits": hits,
        "hit_rate": round(hits / n, 4),
        "hit_lo": w[0] if w else None, "hit_hi": w[1] if w else None,
        "hit_excludes_coinflip": bool(w and (w[0] > 0.5 or w[1] < 0.5)),
    }
    if n < MIN_N:
        out["insufficient"] = True      # sample too small to report a percentage from
    return out


with db.connect() as conn:
    spy = load_series(conn, "SPY")
    with conn.cursor() as cur:
        cur.execute("""
            SELECT c.issuer_entity, c.id, c.as_of, c.confidence_bucket, d.version, c.inputs,
                   (SELECT symbol FROM security_map m WHERE m.entity_id = c.issuer_entity
                      AND m.source = 'sec_company_tickers' ORDER BY confidence DESC LIMIT 1)
            FROM signal_clusters c JOIN signal_definitions d ON d.id = c.definition_id
            ORDER BY c.issuer_entity, c.as_of""")
        rows = cur.fetchall()

    meta = {}       # cluster id -> (bucket, version, inputs)
    by_iv = defaultdict(list)
    for issuer, cid, as_of, bucket, version, inputs, symbol in rows:
        meta[cid] = (bucket, version, inputs, symbol)
        by_iv[(issuer, version)].append((as_of.date(), cid, bucket))

    series: dict[str, object] = {}
    records = []        # one per scored episode entry
    for (_issuer, version), items in by_iv.items():
        for ep in group_episodes(items):
            as_of, cid, bucket = ep[0]
            _b, _v, inputs, symbol = meta[cid]
            if not symbol:
                continue
            if symbol not in series:
                series[symbol] = load_series(conn, symbol)
            sym = series[symbol]
            if not sym.days:
                continue
            contribs = (inputs or {}).get("contributions") or []
            insider = [c for c in contribs if c.get("subtype") == "insider_purchase"]
            stakes = [c for c in contribs if c.get("table") == "stake_events"]
            dollars = sum(float(c["magnitude"]) for c in insider
                          if c.get("magnitude") is not None)
            rec = {
                "version": version, "bucket": bucket, "symbol": symbol, "as_of": as_of,
                "insider_only": bool(insider) and not stakes,
                "distinct_insiders": len({c.get("voice") for c in insider if c.get("voice")}),
                "dollars": dollars,
                "ex": {h: excess_return(sym, spy, as_of, h)[0] for h in HORIZONS},
            }
            records.append(rec)

report: dict = {"episodes_scored": len(records), "min_n_for_a_percentage": MIN_N, "cuts": {}}


def cut(name: str, subset: list[dict]) -> None:
    report["cuts"][name] = {
        f"{h}d": stats([r["ex"][h] for r in subset if r["ex"][h] is not None]) for h in HORIZONS
    }


# --- required: by version, then bucket within version. Never pooled across versions. -----------
for v in (3, 4):
    vs = [r for r in records if r["version"] == v]
    cut(f"v{v}/ALL", vs)
    for b in ("low", "medium", "high"):
        cut(f"v{v}/{b}", [r for r in vs if r["bucket"] == b])

# Pooled is reported ONLY as a clearly-labelled supplement: v4's changelog records "NO
# BEHAVIOURAL CHANGE" - identical logic re-registered after a lint pass - so the version boundary
# is a commit, not a signal. It is never substituted for a per-version figure.
cut("POOLED-SUPPLEMENT/ALL", records)
for b in ("low", "medium", "high"):
    cut(f"POOLED-SUPPLEMENT/{b}", [r for r in records if r["bucket"] == b])

# --- cut (a): insider Form 4 code-P open-market purchases ONLY, no stake filings ---------------
for v in (3, 4):
    cut(f"(a) v{v} insider-P-only", [r for r in records if r["version"] == v and r["insider_only"]])
    cut(f"(a) v{v} has-stake-filing",
        [r for r in records if r["version"] == v and not r["insider_only"]])
cut("(a) POOLED-SUPPLEMENT insider-P-only", [r for r in records if r["insider_only"]])

# --- cut (b): distinct insider count ----------------------------------------------------------
for v in (3, 4):
    for k in (3, 5, 8):
        cut(f"(b) v{v} insiders>={k}",
            [r for r in records if r["version"] == v and r["distinct_insiders"] >= k])
for k in (3, 5, 8):
    cut(f"(b) POOLED-SUPPLEMENT insiders>={k}", [r for r in records if r["distinct_insiders"] >= k])

# --- cut (c): total dollars bought, quartiles -------------------------------------------------
def quartile_cut(label: str, subset: list[dict]) -> None:
    vals = sorted(r["dollars"] for r in subset if r["dollars"] > 0)
    if len(vals) < 8:
        report["cuts"][f"{label} (quartiles)"] = {"note": f"only {len(vals)} episodes with dollars"}
        return
    q1, q2, q3 = (vals[len(vals) // 4], vals[len(vals) // 2], vals[3 * len(vals) // 4])
    report.setdefault("quartile_breaks", {})[label] = {"q1": q1, "q2": q2, "q3": q3}
    bands = [("Q1 smallest", lambda d: 0 < d <= q1), ("Q2", lambda d: q1 < d <= q2),
             ("Q3", lambda d: q2 < d <= q3), ("Q4 largest", lambda d: d > q3)]
    for bname, pred in bands:
        cut(f"{label} {bname}", [r for r in subset if pred(r["dollars"])])


for v in (3, 4):
    quartile_cut(f"(c) v{v}", [r for r in records if r["version"] == v])
quartile_cut("(c) POOLED-SUPPLEMENT", records)

print(json.dumps(report, indent=2, default=str))
