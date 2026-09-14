"""Job 2 STEP 1 — scoreable coverage, computed with the engine's OWN functions.

Deliberately not a hand-written SQL approximation of the scoring rule: `excess_return` picks the
entry (first session strictly after as_of) and the exit (first session at or after entry + horizon
CALENDAR days) itself, and requires BOTH the symbol and SPY to have that exit bar. Re-deriving
that in SQL would produce a coverage table that disagrees with the backtest it is meant to
describe. The third copy is always the one that disagrees.
"""
from __future__ import annotations

import json
from collections import defaultdict

from tradeos import db
from tradeos.backtest.engine import HORIZONS, excess_return, group_episodes
from tradeos.backtest.run import load_series

with db.connect() as conn:
    spy = load_series(conn, "SPY")
    with conn.cursor() as cur:
        cur.execute("""
            SELECT c.issuer_entity, c.id, c.as_of, c.confidence_bucket, d.version,
                   (SELECT symbol FROM security_map m WHERE m.entity_id = c.issuer_entity
                      AND m.source = 'sec_company_tickers' ORDER BY confidence DESC LIMIT 1)
            FROM signal_clusters c JOIN signal_definitions d ON d.id = c.definition_id
            ORDER BY c.issuer_entity, c.as_of""")
        rows = cur.fetchall()

    # Episodes are formed per (issuer, version): a v3 and a v4 cluster on the same issuer are two
    # different signals, not one episode, and must never be merged.
    grouped = defaultdict(list)
    for issuer, cid, as_of, bucket, version, symbol in rows:
        grouped[(issuer, version)].append((as_of.date(), cid, bucket, symbol))

    series: dict[str, object] = {}
    stat = defaultdict(int)
    per_bucket = defaultdict(lambda: defaultdict(int))

    for (_issuer, version), items in grouped.items():
        symbol = items[0][3]
        for episode in group_episodes([(d, cid, b) for (d, cid, b, _s) in items]):
            as_of, _cid, bucket = episode[0]
            key = (version, bucket)
            stat[f"v{version}_episodes"] += 1
            per_bucket[key]["episodes"] += 1
            if not symbol:
                stat[f"v{version}_no_symbol"] += 1
                per_bucket[key]["no_symbol"] += 1
                continue
            if symbol not in series:
                series[symbol] = load_series(conn, symbol)
            sym = series[symbol]
            if not sym.days:
                stat[f"v{version}_no_prices"] += 1
                per_bucket[key]["no_prices"] += 1
                continue
            per_bucket[key]["priced"] += 1
            stat[f"v{version}_priced"] += 1
            for h in HORIZONS:
                val, why = excess_return(sym, spy, as_of, h)
                if val is not None:
                    per_bucket[key][f"scoreable_{h}"] += 1
                    stat[f"v{version}_scoreable_{h}"] += 1
                else:
                    per_bucket[key][f"unscoreable_{h}_{why}"] += 1

# cluster-level counts for the contrast between "clusters" and "scoreable sample"
clusters = defaultdict(lambda: defaultdict(int))
for _i, _c, _a, bucket, version, _s in rows:
    clusters[version][bucket] += 1
    clusters[version]["total"] += 1

print(json.dumps({"clusters": clusters, "episode_stats": stat,
                  "per_version_bucket": {f"v{v}/{b}": dict(d) for (v, b), d in sorted(per_bucket.items())}},
                 indent=2, default=str))
