"""Deterministic explanation template — the always-available path.

Assembles prose purely from a cluster's real fields: what converged, in whose disclosures,
how stale, at what confidence, and the backtested base rate for the bucket (in pattern
language, never as a prediction about a user's position). No directive language; every number
comes from the payload, so it also satisfies the numbers guard by construction.
"""
from __future__ import annotations

from collections import Counter

_CLASS_PHRASE = {
    "insider": "insider purchase",
    "activist": "activist stake filing",
    "passive_stake": "passive >5% stake",
    "institutional_holding": "institutional holding",
}
_QUALIFIER = ("This describes disclosed activity by third parties with the delays labeled. "
              "It is a historical base rate for a pattern, not a prediction about any position, "
              "and past patterns do not guarantee future results.")


def _base_rate_sentence(bucket: str, horizon: int, cal: dict | None) -> str:
    if not cal or cal.get("episodes", 0) == 0:
        return (f"The {horizon}-day horizon has not yet closed for enough {bucket}-bucket "
                f"clusters to state a backtested base rate.")
    n = cal["episodes"]
    if not cal.get("sufficient"):
        return (f"There is insufficient historical sample ({n} episodes) to state a base rate "
                f"for the {bucket} bucket at {horizon} days.")
    pct = round(cal["hit_rate"] * 100)
    year = cal.get("sample_start_year")
    since = f" since {year}" if year else ""
    return (f"Backtested: {bucket}-bucket clusters were followed by positive excess return "
            f"versus SPY {pct}% of the time at {horizon} days, across {n} episodes{since}.")


def render(detail: dict, cal: dict | None, horizon: int) -> str:
    inputs = detail.get("inputs", {})
    contributions = inputs.get("contributions", [])
    classes = detail.get("source_classes", [])
    voices = detail.get("voices", 0)
    sym = detail.get("symbol")
    name = detail.get("name", "the issuer")
    label = f"{name} ({sym})" if sym else name
    window = inputs.get("window_days", 90)
    score_val = detail.get("score")
    score = f"{score_val:.2f}" if isinstance(score_val, (int, float)) else score_val

    class_counts = Counter(c["source_class"] for c in contributions)
    parts = []
    for cls in ("insider", "activist", "passive_stake", "institutional_holding"):
        k = class_counts.get(cls, 0)
        if k:
            phrase = _CLASS_PHRASE[cls]
            parts.append(f"{k} {phrase}{'s' if k != 1 else ''}")
    composition = ", ".join(parts) if parts else "disclosed activity"

    src = "source" if voices == 1 else "independent sources"
    class_names = [c.replace("_", " ") for c in classes]
    if len(class_names) <= 1:
        class_phrase = class_names[0] if class_names else "disclosures"
    elif len(class_names) == 2:
        class_phrase = " and ".join(class_names)
    else:
        class_phrase = ", ".join(class_names[:-1]) + ", and " + class_names[-1]
    prose = (f"{voices} {src} across {class_phrase} disclosures converged on {label} within the "
             f"{window}-day window, for a convergence score of {score} "
             f"({detail.get('confidence_bucket')} confidence). "
             f"The cluster combines {composition}. ")

    fresh = inputs.get("freshest_knowable")
    stale = inputs.get("stalest_knowable")
    if fresh and stale:
        prose += (f"The freshest contributing disclosure became public on {fresh[:10]}, "
                  f"the stalest on {stale[:10]}. ")

    floor = inputs.get("liquidity_floor", {})
    if floor and not floor.get("ok"):
        prose += ("The issuer is below the liquidity floor, so this cluster is excluded from "
                  "the default feed and treated with lower confidence. ")

    prose += _base_rate_sentence(detail.get("confidence_bucket", "low"), horizon, cal) + " "
    prose += _QUALIFIER
    return prose
