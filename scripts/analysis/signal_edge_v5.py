"""Does the PURE-INSIDER signal have an edge? Read-only, and deliberately identical in method
to `signal_edge.py` so the two answers are comparable rather than merely adjacent.

Same conventions, same functions, same thresholds:
  * entry = close of the first trading day AFTER the cluster's as_of; exit = first session on or
    after entry + horizon calendar days; metric = excess return vs SPY; a hit is excess > 0
    (`backtest.engine.excess_return`, unchanged);
  * `ledger.mean_ci` for MEANS and `engine.wilson_interval` for PROPORTIONS. These are not
    interchangeable — a Wilson interval is a statement about a proportion, so applying it to a
    mean excess return would be a category error. Hit rate gets Wilson; mean excess gets the
    sample-mean interval;
  * MIN_N = 30: below it no percentage is reported at all, only the count.

The episodes come from `compute_v5.py`'s artifact rather than from `signal_clusters`, because
v5 is deliberately not stored there (see that script's docstring). Grouping is already done —
one row per episode entry, keyed on (issuer, definition), which is the same
never-pool-two-definitions rule `signal_edge.py` had to reimpose by hand on v3/v4.
"""
from __future__ import annotations

import json
import statistics
from collections import defaultdict
from datetime import date

from tradeos import db
from tradeos.backtest.engine import HORIZONS, Series, excess_return, wilson_interval
from tradeos.ledger import mean_ci, proportion_z, sample_needed

MIN_N = 30
ARTIFACT = "docs/analysis/v5_episodes.json"
ARTIFACT_WITH_ROUTINE = "docs/analysis/v5_episodes_with_routine.json"
TARGET_EDGE = 0.01          # the 1%-per-episode edge the power check asks about
# SPY is the product's benchmark everywhere else, so it stays the headline. IWM (Russell
# 2000) and IJR (S&P SmallCap 600) are here to test the one alternative explanation that
# would void the whole result: insider buying concentrates in small caps, and excess-vs-SPY
# applies no size or beta control, so a small-cap drawdown would produce this shape with no
# insider content at all. CMP benchmark against characteristic-matched portfolios; this is
# the nearest control this database can build.
BENCHMARKS = ("SPY", "IWM", "IJR")


def stats(vals: list[float]) -> dict:
    """Mean excess + its interval, and hit rate + its Wilson interval. Never a bare rate."""
    n = len(vals)
    if n == 0:
        return {"n": 0, "insufficient": True}
    hits = sum(1 for v in vals if v > 0)
    m, w = mean_ci(vals), wilson_interval(hits, n)
    out = {
        "n": n, "mean_excess": m["mean"], "mean_lo": m["lo"], "mean_hi": m["hi"],
        "sd": m["sd"], "mean_excludes_zero": m["significant"],
        "hits": hits, "hit_rate": round(hits / n, 4),
        "hit_lo": w[0] if w else None, "hit_hi": w[1] if w else None,
        "hit_excludes_coinflip": bool(w and (w[0] > 0.5 or w[1] < 0.5)),
        "hit_z_vs_coinflip": proportion_z(hits, n),
    }
    if n < MIN_N:
        out["insufficient"] = True          # sample too small to report a percentage from
    return out


def load_series(conn, symbols: set[str]) -> dict[str, Series]:
    """Every close for every symbol in one query. 1,900 separate round trips would dominate."""
    rows: dict[str, list] = defaultdict(list)
    with conn.cursor() as cur:
        cur.execute("SELECT symbol, day, close FROM prices_eod WHERE symbol = ANY(%s) ORDER BY day",
                    (sorted(symbols),))
        for symbol, day, close in cur:
            rows[symbol].append((day, close))
    return {s: Series.from_rows(r) for s, r in rows.items()}


def score(records: list[dict], series: dict[str, Series], spy: Series) -> list[dict]:
    """Attach excess returns at each horizon. `why` is kept so coverage can say WHY a horizon
    is missing — "still open" and "no price history" are different facts and were conflated
    once before in this codebase (`ledger.UNSCOREABLE_REASONS`)."""
    out = []
    for r in records:
        sym = series.get(r["symbol"])
        as_of = date.fromisoformat(r["as_of"])
        if sym is None or not sym.days:
            out.append({**r, "ex": dict.fromkeys(HORIZONS),
                        "why": dict.fromkeys(HORIZONS, "no_price_history")})
            continue
        ex, why = {}, {}
        for h in HORIZONS:
            ex[h], why[h] = excess_return(sym, spy, as_of, h)
        out.append({**r, "ex": ex, "why": why})
    return out


def _spy_rows(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT day, close FROM prices_eod WHERE symbol = 'SPY' ORDER BY day")
        return cur.fetchall()


def main() -> None:
    with open(ARTIFACT) as fh:
        art = json.load(fh)
    try:
        with open(ARTIFACT_WITH_ROUTINE) as fh:
            art_routine = json.load(fh)
    except FileNotFoundError:
        art_routine = None

    with db.connect() as conn:
        symbols = {r["symbol"] for r in art["rows"]}
        if art_routine:
            symbols |= {r["symbol"] for r in art_routine["rows"]}
        series = load_series(conn, symbols | set(BENCHMARKS))
        spy = series["SPY"]
        records = score(art["rows"], series, spy)
        records_routine = score(art_routine["rows"], series, spy) if art_routine else []
        benchmarks = {b: score(art["rows"], series, series[b]) for b in BENCHMARKS
                      if b in series and series[b].days}

    report: dict = {
        "definition": art["definition"], "code_hash": art["code_hash"][:16],
        "min_n_for_a_percentage": MIN_N,
        "episodes_total": len(records),
        "distinct_symbols": art["distinct_symbols"], "distinct_issuers": art["distinct_issuers"],
        "span": art["span"], "label_counts": art["label_counts"],
        "gate_clusters": art["gate_clusters"], "published_clusters": art["published_clusters"],
        "floor_rejected": art["floor_rejected"],
        "floor_verification": art["floor_verification"],
        "symbols_with_no_price_series": sorted(
            {r["symbol"] for r in records if r["why"][30] == "no_price_history"}),
    }

    # ---------------------------------------------------------- STEP 1: coverage, no statistics
    coverage = {}
    for bucket in ("low", "medium", "high", "ALL"):
        subset = records if bucket == "ALL" else [r for r in records if r["bucket"] == bucket]
        row: dict = {"episodes": len(subset)}
        for h in HORIZONS:
            closed = [r for r in subset if r["ex"][h] is not None]
            reasons: dict[str, int] = defaultdict(int)
            for r in subset:
                if r["ex"][h] is None:
                    reasons[r["why"][h]] += 1
            row[f"{h}d"] = {"scoreable": len(closed), "sufficient": len(closed) >= MIN_N,
                            "unscoreable_reasons": dict(reasons)}
        coverage[bucket] = row
    report["coverage"] = coverage

    # ---------------------------------------------------------- STEP 2 + 3: the cuts
    cuts: dict[str, dict] = {}

    fingerprints: dict[str, tuple] = {}

    def cut(name: str, subset: list[dict], benchmark: str = "SPY") -> None:
        cuts[name] = {f"{h}d": stats([r["ex"][h] for r in subset if r["ex"][h] is not None])
                      for h in HORIZONS}
        # What set of episodes, measured against what, this cut actually tested. Three of the
        # named cuts below are the SAME episodes under different names — `(b) insiders>=2` is
        # every episode because min_voices is 2, and the routine CONTROL is identical because
        # no episode contains a routine voice — so counting them as separate tests would
        # inflate both the test count and the significant count.
        fingerprints[name] = (benchmark,
                              tuple(sorted((r["issuer"], r["as_of"]) for r in subset)))

    cut("ALL", records)
    for b in ("low", "medium", "high"):
        cut(b, [r for r in records if r["bucket"] == b])

    # --- cut (a): the CMP headline. opportunistic-only vs every insider including routine ----
    def n_label(r: dict, label: str) -> int:
        return int(r["classifications"].get(label, 0))

    cut("(a) opportunistic voices only",
        [r for r in records if n_label(r, "opportunistic") > 0 and n_label(r, "unclassified") == 0])
    cut("(a) at least one opportunistic voice",
        [r for r in records if n_label(r, "opportunistic") > 0])
    cut("(a) no opportunistic voice (all unclassified)",
        [r for r in records if n_label(r, "opportunistic") == 0])
    if records_routine:
        cut("(a) CONTROL all insiders incl. routine", records_routine)
        cut("(a) CONTROL episodes containing a routine voice",
            [r for r in records_routine if n_label(r, "routine") > 0])

    # --- cut (b): Lakonishok & Lee. does agreement among insiders help? ---------------------
    for k in (2, 3, 5, 8):
        cut(f"(b) insiders>={k}", [r for r in records if r["distinct_insiders"] >= k])

    # --- cut (c): total dollars committed, quartiles ----------------------------------------
    vals = sorted(r["dollars"] for r in records if r["dollars"] > 0)
    if len(vals) >= 8:
        q1, q2, q3 = vals[len(vals) // 4], vals[len(vals) // 2], vals[3 * len(vals) // 4]
        report["dollar_quartile_breaks"] = {"q1": q1, "q2": q2, "q3": q3,
                                            "episodes_with_dollars": len(vals)}
        for name, pred in (("Q1 smallest", lambda d: 0 < d <= q1),
                           ("Q2", lambda d: q1 < d <= q2),
                           ("Q3", lambda d: q2 < d <= q3),
                           ("Q4 largest", lambda d: d > q3)):
            cut(f"(c) {name}", [r for r in records if pred(r["dollars"])])
    # --- robustness. Reported whatever they say, and counted in the tally below. ------------
    for bench, recs in benchmarks.items():
        if bench == "SPY":
            continue
        cut(f"[robust] vs {bench}", recs, benchmark=bench)
    report["benchmark_itself_vs_spy"] = {
        bench: {f"{h}d": round(statistics.fmean(v), 5) if (
            v := [x for x in (excess_return(series[bench], spy, date.fromisoformat(r["as_of"]), h)[0]
                              for r in art["rows"]) if x is not None]) else None
                for h in HORIZONS}
        for bench in benchmarks if bench != "SPY"}

    for y in sorted({r["as_of"][:4] for r in records}):
        cut(f"[robust] entry year {y}", [r for r in records if r["as_of"][:4] == y])

    lengths = sorted(r["clusters_in_episode"] for r in records)
    t1, t2 = lengths[len(lengths) // 3], lengths[2 * len(lengths) // 3]
    report["episode_length_terciles"] = {"t1": t1, "t2": t2,
                                         "median": lengths[len(lengths) // 2], "max": lengths[-1]}
    cut(f"[robust] episode length <={t1}", [r for r in records if r["clusters_in_episode"] <= t1])
    cut(f"[robust] episode length {t1 + 1}-{t2}",
        [r for r in records if t1 < r["clusters_in_episode"] <= t2])
    cut(f"[robust] episode length >{t2}", [r for r in records if r["clusters_in_episode"] > t2])
    report["cuts"] = cuts

    # ---------------------------------------------------------- STEP 4: multiple testing
    # Every cut x horizon that reached a usable sample is a test, and each carries its own 5%
    # chance of clearing zero on noise alone. A search that finds no more than chance would
    # produce has found nothing, however good the best single number looks.
    # Duplicates first. `(b) insiders>=2` is every episode (min_voices IS 2) and the routine
    # CONTROL is every episode (no episode contains a routine voice), so three names describe
    # one test. Counting them three times would inflate the denominator AND the numerator.
    seen: dict[tuple, str] = {}
    duplicates: dict[str, str] = {}
    for name, fp in fingerprints.items():
        if fp in seen:
            duplicates[name] = seen[fp]
        else:
            seen[fp] = name

    tested = [(name, h, s) for name, per_h in cuts.items() for h, s in per_h.items()
              if s.get("n", 0) >= MIN_N and name not in duplicates]
    significant = [(n, h, s) for n, h, s in tested if s["mean_excludes_zero"]]
    hit_significant = [(n, h, s) for n, h, s in tested if s["hit_excludes_coinflip"]]
    negative = [t for t in significant if t[2]["mean_excess"] < 0]
    report["multiple_testing"] = {
        "duplicate_cuts_excluded": duplicates,
        "tests_with_n_at_least_30": len(tested),
        "expected_false_positives_at_alpha_0.05": round(0.05 * len(tested), 2),
        "mean_excess_intervals_excluding_zero": len(significant),
        "of_which_negative": len(negative),
        "of_which_positive": len(significant) - len(negative),
        "exceeds_chance": len(significant) > 0.05 * len(tested),
        # The count is the weaker argument, because these cuts are heavily NESTED — `low` is
        # 78% of ALL, the quartiles partition it, the benchmark rows are the same episodes
        # against a different index — so the effective number of independent tests is well
        # below the raw count, and both numbers above are inflated by the same nesting. The
        # argument that does not depend on the count is DIRECTION: a multiple-testing artifact
        # scatters significant results either side of zero, and every one of these is on the
        # same side.
        "all_significant_share_one_direction": len(significant) > 0 and len(negative) in (0, len(significant)),
        "significant_cuts": [{"cut": n, "horizon": h, "n": s["n"], "mean": s["mean_excess"],
                              "lo": s["mean_lo"], "hi": s["mean_hi"]} for n, h, s in significant],
        "hit_rate_intervals_excluding_coinflip": len(hit_significant),
        "hit_rate_significant_cuts": [{"cut": n, "horizon": h, "n": s["n"],
                                       "hit_rate": s["hit_rate"], "z": s["hit_z_vs_coinflip"],
                                       "direction": "above" if s["hit_rate"] > 0.5 else "below"}
                                      for n, h, s in hit_significant],
    }

    # ---------------------------------------------------------- STEP 5: power
    # An underpowered positive is worthless, so this is computed from THIS sample's own
    # dispersion rather than quoted from the v3 analysis.
    power = {}
    for h in HORIZONS:
        vals_h = [r["ex"][h] for r in records if r["ex"][h] is not None]
        if len(vals_h) < 2:
            power[f"{h}d"] = {"n": len(vals_h), "insufficient": True}
            continue
        sd = statistics.stdev(vals_h)
        need = sample_needed(sd, TARGET_EDGE)
        power[f"{h}d"] = {"n": len(vals_h), "sd": round(sd, 5),
                          "episodes_needed_for_1pct_edge": need,
                          "reached": bool(need and len(vals_h) >= need),
                          "shortfall": (need - len(vals_h)) if need and need > len(vals_h) else 0}
    report["power"] = power

    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
