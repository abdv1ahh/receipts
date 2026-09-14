"""Compute the pure-insider signal's clusters and episodes. READ-ONLY.

WHY THIS DOES NOT USE `definitions.compute_and_store`. That driver writes into
`signal_clusters`, and 30 read sites across 12 live modules query that table with no
definition filter — `/api/signals` is `WHERE c.as_of = %s` and nothing more. v3 and v4 do not
collide today only because they were computed on disjoint as_of days (measured: 0 colliding
(issuer, as_of) pairs). A third definition replayed over v3's range would collide on every one
of its 419 days, and the Smart Money feed, the dashboard, the Morning Brief, alerts and the
PUBLIC methodology calibration would each double-count. So the clusters are computed in
memory, with the same functions, and the episodes are written to a JSON artifact instead.

WHAT IS IDENTICAL TO THE REAL DRIVER, so the numbers are the engine's own:
  * params come from the REGISTERED definition row via `require_definition`, so the module
    hash guard applies exactly as it would to a stored compute (decision #24);
  * scoring is `convergence.score_cluster`, unmodified;
  * bucketing is `convergence.bucket_for`;
  * a sub-floor cluster does not publish at all, matching `compute_and_store`;
  * episodes are `backtest.engine.group_episodes`, EPISODE_GAP_DAYS = 14.

TWO DELIBERATE DIFFERENCES, both measured rather than assumed:

1. **Each purchase is classified once**, against the insider's history as it was knowable at
   that purchase's OWN `knowable_time`, rather than re-classified at every as_of the purchase
   appears in. Re-classifying 60,708 purchases across every day of a 90-day window is ~5.5M
   classifications for a label that cannot meaningfully move: a Form 4 is due within two
   business days, so an insider's earlier trades in the same issuer are almost always public
   before this one is. Where it does differ, fixing the label at the purchase's own
   knowable_time sees STRICTLY LESS history than a later as_of would, so the error can only
   push a trade from ROUTINE toward UNCLASSIFIED — never the reverse, and never toward seeing
   the future.

2. **The liquidity floor is computed in memory** rather than by 251,688 separate SQL
   percentile queries. `LiquidityFloor` is a replica, and because a replica that drifts is
   worse than no replica at all (CLAUDE.md §0b2) it is CHECKED against the real
   `convergence.passes_liquidity_floor` on a random sample every run, and the agreement rate
   is printed into the artifact. A mismatch aborts.

TWO STAGES, because of a chicken and egg. The floor needs prices, and v5 reaches 3,645 issuers
where only 501 symbols were priced. Stage A reports the symbols the gate admits so they can be
backfilled; stage B applies the floor and writes the episodes.
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
from array import array
from bisect import bisect_left, bisect_right
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta

from tradeos import db
from tradeos.backtest.engine import EPISODE_GAP_DAYS, group_episodes
from tradeos.signals import convergence, definitions, insider, opportunistic

FLOOR_VERIFY_SAMPLE = 300


def artifact_path(include_routine: bool) -> str:
    return ("docs/analysis/v5_episodes_with_routine.json" if include_routine
            else "docs/analysis/v5_episodes.json")


# --------------------------------------------------------------------------- liquidity floor

class LiquidityFloor:
    """In-memory replica of `convergence._passes_liquidity_floor`, verified against it.

    Note what the real SQL actually does, because it is easy to get wrong: it joins
    `security_map` on ENTITY and takes the median over the rows of EVERY symbol mapped to that
    entity, not over one chosen ticker. 1,473 of 8,031 entities map to more than one symbol —
    dual share classes, preferreds, units — so pooling is not an edge case here. The episode's
    RETURN is still measured on the single highest-confidence symbol, because that is what
    `backtest/run.py` and `signal_edge.py` do; the floor and the return legitimately look at
    different things and this class reproduces the floor, not the return.
    """

    def __init__(self, conn, params: dict):
        self.window = params["liquidity_window_days"]
        self.threshold = params["liquidity_floor_usd"]
        self.by_entity: dict[int, tuple[array, array]] = {}
        with conn.cursor() as cur:
            cur.execute(
                """SELECT m.entity_id, p.day, p.close * p.volume
                   FROM prices_eod p JOIN security_map m ON m.symbol = p.symbol
                   WHERE m.source = 'sec_company_tickers' AND p.volume IS NOT NULL
                   ORDER BY m.entity_id, p.day""")
            days: dict[int, array] = defaultdict(lambda: array("i"))
            vals: dict[int, array] = defaultdict(lambda: array("d"))
            for entity, day, dollar_volume in cur:
                days[entity].append(day.toordinal())
                vals[entity].append(float(dollar_volume))
        self.by_entity = {e: (days[e], vals[e]) for e in days}

    def ok(self, entity: int, day: date) -> bool:
        pair = self.by_entity.get(entity)
        if pair is None:
            return False                    # no price history -> below floor, as the SQL says
        days, vals = pair
        hi = bisect_right(days, day.toordinal())
        lo = bisect_right(days, (day - timedelta(days=self.window)).toordinal())
        if hi <= lo:
            return False
        return statistics.median(vals[lo:hi]) >= self.threshold

    def verify(self, conn, samples: list[tuple[int, date]], params: dict) -> dict:
        """Ask the real SQL the same questions and count disagreements."""
        mismatches = []
        for entity, day in samples:
            as_of = datetime(day.year, day.month, day.day, 23, 59, 59, tzinfo=UTC)
            truth = convergence.passes_liquidity_floor(conn, entity, as_of, params)
            if truth != self.ok(entity, day):
                mismatches.append({"entity": entity, "day": day.isoformat(), "sql": truth})
        return {"checked": len(samples), "mismatches": len(mismatches),
                "examples": mismatches[:5]}


# --------------------------------------------------------------------------- gather + replay

def load_purchases(conn):
    """Every code-P open-market purchase with a resolved issuer, plus its CMP label.

    `acquired_disposed = 'A'` alongside code P is how `convergence.gather_events` already
    identifies a purchase; codes S (sale), M (option exercise), A (grant) and F (tax
    withholding) are excluded by never being selected.
    """
    with conn.cursor() as cur:
        cur.execute(
            """SELECT id, issuer_entity, issuer_cik, owner_cik, shares, price_per_share,
                      knowable_time, event_time
               FROM insider_transactions
               WHERE issuer_entity IS NOT NULL
                 AND transaction_code = 'P' AND acquired_disposed = 'A'
               ORDER BY knowable_time""")
        purchases = cur.fetchall()

        # History for classification: EVERY transaction code, because a sell-every-March
        # insider is as scheduled as a buy-every-March one (opportunistic.py deviation 2),
        # and keyed on issuer_cik rather than issuer_entity — see the long note in
        # `insider.gather_events`. Entity-keyed history is NULL on 94,775 rows concentrated in
        # 2021-2023 and starves the three-year lookback: 1,833 opportunistic labels against
        # 10,882 from the same rule on the same trades.
        cur.execute(
            """SELECT issuer_cik, owner_cik, event_time, knowable_time
               FROM insider_transactions""")
        history: dict[tuple[str, str], list] = defaultdict(list)
        for issuer_cik, owner, event_time, knowable in cur:
            history[(issuer_cik, owner)].append((event_time, knowable))

    out, counts = [], defaultdict(int)
    for tid, issuer, issuer_cik, owner, shares, price, knowable, event_time in purchases:
        visible = [e for e, k in history[(issuer_cik, owner)] if k <= knowable]
        label = opportunistic.classify_insider(visible, event_time)
        counts[label] += 1
        out.append({
            "id": tid, "issuer": issuer, "owner": owner, "knowable": knowable,
            "knowable_day": knowable.date(), "label": label,
            "magnitude": float(shares * price) if (shares is not None and price is not None) else None,
        })
    return out, dict(counts)


def clusters_for_issuer(purchases: list[dict], params: dict, today: date, include_routine: bool):
    """Replay every business day on which this issuer could have clustered.

    A purchase knowable on day k sits inside the 90-day window for as_of in [k, k+89], so the
    candidate days are that union rather than the whole calendar — the same answer as scanning
    every day, without scanning 4,000 empty ones per issuer.
    """
    window = params["window_days"]
    min_voices = params["gate"]["min_voices"]
    keys = [p["knowable"] for p in purchases]           # already sorted by knowable_time

    days: set[date] = set()
    for p in purchases:
        k = p["knowable_day"]
        for offset in range(window):
            d = k + timedelta(days=offset)
            if d > today:
                break
            if d.weekday() < 5:
                days.add(d)

    by_day = []
    for d in sorted(days):
        as_of = datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=UTC)
        lo = bisect_right(keys, as_of - timedelta(days=window))
        hi = bisect_left(keys, as_of + timedelta(microseconds=1))
        in_window = purchases[lo:hi]
        # Routine insiders are dropped entirely: not a voice, and not a contribution. The
        # --include-routine variant keeps them, which is cut (a)'s control arm.
        scored = (in_window if include_routine
                  else [p for p in in_window if opportunistic.counts_toward_gate(p["label"])])
        if len({p["owner"] for p in scored}) < min_voices:
            continue                        # cheap pre-check before building Events
        events = [convergence.Event(
            subtype="insider_purchase", voice_key=f"insider:{p['owner']}",
            knowable_time=p["knowable"], magnitude=p["magnitude"],
            ref={"id": p["id"], "classification": p["label"]}) for p in scored]
        result = convergence.score_cluster(events, as_of, params)
        if not result.passes_gate:
            continue
        labels: dict[str, int] = defaultdict(int)
        for p in scored:
            labels[p["label"]] += 1
        by_day.append({
            "as_of": d, "result": result, "labels": dict(labels),
            "dollars": sum(p["magnitude"] for p in scored if p["magnitude"]),
            "distinct_insiders": len({p["owner"] for p in scored}),
        })
    return by_day


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=("a", "b"), default="b",
                    help="a = gate only, report symbols needing prices; b = apply the floor")
    ap.add_argument("--include-routine", action="store_true",
                    help="cut (a) control arm: count routine insiders as voices too")
    args = ap.parse_args()
    say = lambda m: print(m, file=sys.stderr)  # noqa: E731 - local shorthand, stderr only

    with db.connect() as conn:
        defn = definitions.require_definition(conn, insider.NAME, insider.module_code_hash())
        params = defn["params"]
        say(f"# {insider.NAME} v{defn['version']}  hash={defn['code_hash'][:12]}  "
            f"include_routine={args.include_routine}")
        say(f"# gate={params['gate']}  floor=${params['liquidity_floor_usd']:,.0f}")

        purchases, label_counts = load_purchases(conn)
        say(f"# {len(purchases):,} code-P purchases  labels={label_counts}")

        with conn.cursor() as cur:
            cur.execute("""SELECT DISTINCT ON (entity_id) entity_id, symbol FROM security_map
                           WHERE source = 'sec_company_tickers' AND symbol IS NOT NULL
                           ORDER BY entity_id, confidence DESC""")
            symbol_of = dict(cur.fetchall())

        by_issuer: dict[int, list[dict]] = defaultdict(list)
        for p in purchases:
            by_issuer[p["issuer"]].append(p)

        today = date.today()
        gate_passing: dict[int, list[dict]] = {}
        for i, (issuer, rows) in enumerate(by_issuer.items(), 1):
            if i % 1000 == 0:
                say(f"#   {i:,}/{len(by_issuer):,} issuers")
            found = clusters_for_issuer(rows, params, today, args.include_routine)
            if found:
                gate_passing[issuer] = found

        n_clusters = sum(len(v) for v in gate_passing.values())
        symbols = {symbol_of.get(i) for i in gate_passing} - {None}
        say(f"# GATE: {n_clusters:,} clusters / {len(gate_passing):,} issuers / {len(symbols):,} symbols")

        if args.stage == "a":
            with conn.cursor() as cur:
                cur.execute("SELECT DISTINCT symbol FROM prices_eod")
                priced = {r[0] for r in cur.fetchall()}
            need = sorted(symbols - priced)
            print(json.dumps({
                "stage": "a", "gate_clusters": n_clusters, "gate_issuers": len(gate_passing),
                "symbols_total": len(symbols), "symbols_priced": len(symbols & priced),
                "symbols_needing_prices": len(need), "need": need,
                "issuers_without_symbol": sum(1 for i in gate_passing if not symbol_of.get(i)),
                "label_counts": label_counts}, indent=2))
            return

        # ---- stage b: the liquidity floor, then episodes -------------------------------
        say("# loading dollar-volume series for the floor...")
        floor = LiquidityFloor(conn, params)
        say(f"# floor loaded for {len(floor.by_entity):,} entities; verifying against SQL...")

        all_pairs = [(i, c["as_of"]) for i, found in gate_passing.items() for c in found]
        # Seeded so the verification sample is the same on every run and a reported
        # agreement rate is reproducible. Not a security context.
        rng = random.Random(20260915)  # noqa: S311
        check = floor.verify(conn, rng.sample(all_pairs, min(FLOOR_VERIFY_SAMPLE, len(all_pairs))),
                             params)
        say(f"# floor verification: {check}")
        if check["mismatches"]:
            raise SystemExit(f"liquidity floor replica disagrees with SQL: {check}")

        floor_rejected = no_symbol = next_id = 0
        published: dict[int, list] = defaultdict(list)
        meta: dict[int, dict] = {}
        for issuer, found in gate_passing.items():
            symbol = symbol_of.get(issuer)
            if not symbol:
                no_symbol += len(found)
                continue
            for c in found:
                if not floor.ok(issuer, c["as_of"]):
                    floor_rejected += 1     # sub-floor clusters do not publish at all
                    continue
                next_id += 1
                bucket = convergence.bucket_for(c["result"].score, True, params)
                meta[next_id] = {**c, "symbol": symbol, "bucket": bucket}
                published[issuer].append((c["as_of"], next_id, bucket))

        episodes = []
        for issuer, items in published.items():
            for ep in group_episodes(items, EPISODE_GAP_DAYS):
                as_of, cid, bucket = ep[0]
                m = meta[cid]
                episodes.append({
                    "issuer": issuer, "as_of": as_of.isoformat(), "symbol": m["symbol"],
                    "score": m["result"].score, "bucket": bucket, "voices": m["result"].voices,
                    "distinct_insiders": m["distinct_insiders"], "dollars": m["dollars"],
                    "classifications": m["labels"], "clusters_in_episode": len(ep),
                })

    out = {
        "definition": f"{insider.NAME}-v{defn['version']}",
        "code_hash": defn["code_hash"], "include_routine": args.include_routine,
        "params": params,
        "gate_clusters": n_clusters,
        "published_clusters": sum(len(v) for v in published.values()),
        "floor_rejected": floor_rejected, "clusters_without_symbol": no_symbol,
        "floor_verification": check,
        "episodes": len(episodes), "distinct_symbols": len({e["symbol"] for e in episodes}),
        "distinct_issuers": len(published), "episode_gap_days": EPISODE_GAP_DAYS,
        "label_counts": label_counts,
        "span": [min((e["as_of"] for e in episodes), default=None),
                 max((e["as_of"] for e in episodes), default=None)],
        "rows": episodes,
    }
    path = artifact_path(args.include_routine)
    with open(path, "w") as fh:
        json.dump(out, fh, indent=1, default=str)
    print(json.dumps({k: v for k, v in out.items() if k not in ("rows", "params")},
                     indent=2, default=str))
    say(f"# wrote {path}")


if __name__ == "__main__":
    main()
