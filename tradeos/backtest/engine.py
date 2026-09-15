"""Pure backtest math. No DB, no network — deterministic functions over price series and
cluster lists, so the characterization and look-ahead tests can freeze exact outputs.

Conventions (decision #25):
  entry = close of the first trading day AFTER the cluster's as_of date
  exit  = close of the first trading day on/after (entry + horizon calendar days)
  metric = excess return vs SPY over the horizon; a "hit" = excess > 0
"""
from __future__ import annotations

import bisect
import math
import statistics
from dataclasses import dataclass
from datetime import date, timedelta

HORIZONS = (30, 90, 180)
EPISODE_GAP_DAYS = 14        # clusters on one issuer within this gap = one episode (decision #26)
MIN_EPISODES = 30            # below this a bucket shows "insufficient sample" (never a rate)
Z95 = 1.959963984540054


@dataclass
class Series:
    """A symbol's daily closes, sorted by day."""
    days: list[date]
    close: dict[date, float]

    @classmethod
    def from_rows(cls, rows: list[tuple[date, float]]) -> Series:
        rows = sorted(rows)
        return cls([d for d, _ in rows], {d: float(c) for d, c in rows})

    @property
    def last_day(self) -> date | None:
        return self.days[-1] if self.days else None


def _first_gt(days: list[date], target: date) -> date | None:
    i = bisect.bisect_right(days, target)
    return days[i] if i < len(days) else None


def _first_ge(days: list[date], target: date) -> date | None:
    i = bisect.bisect_left(days, target)
    return days[i] if i < len(days) else None


def excess_return(sym: Series, spy: Series, as_of_day: date, horizon_days: int):
    """Excess return vs SPY over the horizon, or None if the pair cannot be resolved (missing
    price history, or the horizon has not closed). The second element flags WHY it is None so
    the driver can separate 'horizon still open' from 'excluded for missing price history'.

    FOUR reasons, not two, and the split is load bearing. Two of them are facts about the SUBJECT
    and two are facts about OUR BENCHMARK INGESTION, and a caller cannot be held to the second
    kind. This used to return `no_entry_price` both when the subject had no session after the
    claim and when the benchmark was missing that one session; Receipts read the merged answer as
    a permanent property of the subject and sealed `unscoreable` on a healthy, liquid symbol
    because SPY had a single hole -- with a note naming the wrong ticker, and the append-only
    trigger making both unchangeable. Whose gap it is has to survive the return statement.
    """
    entry = _first_gt(sym.days, as_of_day)          # first trading day strictly after as_of
    if entry is None:
        return None, "no_entry_price"                  # the SUBJECT has no session after as_of
    if entry not in spy.close:
        return None, "no_benchmark_entry_price"        # ours: the benchmark is missing that session
    target = entry + timedelta(days=horizon_days)
    sym_exit = _first_ge(sym.days, target)
    if sym_exit is None:
        return None, "horizon_open_or_delisted"        # the SUBJECT has not reached the horizon
    spy_exit = _first_ge(spy.days, target)
    if spy_exit is None:
        return None, "no_benchmark_exit_price"         # ours: the benchmark has not reached it
    sym_ret = sym.close[sym_exit] / sym.close[entry] - 1.0
    spy_ret = spy.close[spy_exit] / spy.close[entry] - 1.0
    return round(sym_ret - spy_ret, 6), "ok"


def entry_day_after(sym: Series, as_of_day: date) -> date | None:
    return _first_gt(sym.days, as_of_day)


def exit_day_for(sym: Series, entry: date, horizon_days: int) -> date | None:
    """The session a horizon closes on: the first session at or after entry + horizon_days.

    The companion to `entry_day_after`, and public for the same reason. `excess_return` already
    picks these two days internally, but a caller that has to SHOW its arithmetic — an investor
    checking a resolved call with a calculator — needs the days themselves, not only the number
    that came out. Without this they would each re-derive it, and the third copy is always the one
    that disagrees.

    Note the horizon is in CALENDAR days, matching `excess_return`, so a 30 day horizon closes on
    the first session on or after the thirtieth day rather than thirty sessions later.
    """
    return _first_ge(sym.days, entry + timedelta(days=horizon_days))


def group_episodes(clusters: list[tuple[date, int, str]], gap_days: int = EPISODE_GAP_DAYS):
    """clusters = [(as_of_day, cluster_id, bucket)]. Returns a list of episodes (each a list of
    those tuples). A new episode starts when the gap from the previous cluster exceeds gap_days.
    The episode is entered at its first (earliest) cluster."""
    episodes: list[list[tuple[date, int, str]]] = []
    current: list[tuple[date, int, str]] = []
    for c in sorted(clusters):
        if current and (c[0] - current[-1][0]).days > gap_days:
            episodes.append(current)
            current = []
        current.append(c)
    if current:
        episodes.append(current)
    return episodes


def wilson_interval(hits: int, n: int, z: float = Z95) -> tuple[float, float] | None:
    """Wilson score 95% interval on a hit rate — honest for small n (never a bare point rate)."""
    if n == 0:
        return None
    phat = hits / n
    denom = 1 + z * z / n
    center = (phat + z * z / (2 * n)) / denom
    margin = z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n)) / denom
    return (round(max(0.0, center - margin), 4), round(min(1.0, center + margin), 4))


def bucket_calibration(excess_values: list[float]) -> dict:
    """Calibration for one bucket at one horizon over its resolved episode excess returns."""
    n = len(excess_values)
    if n == 0:
        return {"episodes": 0, "sufficient": False, "hit_rate": None, "ci95": None,
                "mean_excess": None, "median_excess": None}
    hits = sum(1 for v in excess_values if v > 0)
    return {
        "episodes": n,
        "sufficient": n >= MIN_EPISODES,
        "hits": hits,
        "hit_rate": round(hits / n, 4),
        "ci95": wilson_interval(hits, n),
        "mean_excess": round(statistics.fmean(excess_values), 6),
        "median_excess": round(statistics.median(excess_values), 6),
        "min_episodes_for_display": MIN_EPISODES,
    }
