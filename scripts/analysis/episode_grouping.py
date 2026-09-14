"""Does run_backtest's episode grouping pool the two definition versions together?

`_by_issuer` keys on issuer ALONE. If a v3 and a v4 cluster on the same issuer fall within
EPISODE_GAP_DAYS, they become ONE episode and only the earliest is scored — so the per-version
split the analysis is required to report would be decided by which version happened to fire first.
This measures how often that actually happens before anything is claimed either way.
"""
from __future__ import annotations

from collections import defaultdict

from tradeos import db
from tradeos.backtest.engine import group_episodes

with db.connect() as conn:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT c.issuer_entity, c.id, c.as_of, c.confidence_bucket, d.version
            FROM signal_clusters c JOIN signal_definitions d ON d.id = c.definition_id
            ORDER BY c.issuer_entity, c.as_of""")
        rows = cur.fetchall()

by_issuer = defaultdict(list)
for issuer, cid, as_of, bucket, version in rows:
    by_issuer[issuer].append((as_of.date(), cid, bucket, version))

ver_of = {cid: v for _i, cid, _a, _b, v in rows}

episodes = 0
entry_version = defaultdict(int)
mixed = 0
for items in by_issuer.values():
    for ep in group_episodes([(d, cid, b) for (d, cid, b, _v) in items]):
        episodes += 1
        vs = {ver_of[cid] for (_d, cid, _b) in ep}
        entry_version[ver_of[ep[0][1]]] += 1
        if len(vs) > 1:
            mixed += 1

print("issuers:", len(by_issuer))
print("episodes (run_backtest's actual grouping, issuer-only):", episodes)
print("episodes whose member clusters span BOTH versions:", mixed)
print("episode entry cluster by version:", dict(entry_version))
