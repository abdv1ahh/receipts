"""The two mechanical guards on any model output (docs/threat-models/explanation.md).

numbers_guard: every numeric token in the output must trace to a value in the input payload
  (with formatting tolerance) — the model may not introduce a measurement.
directive_guard: the output may not contain advice / recommendation / second-person-position
  vocabulary — the product describes, it never tells a user what to do.

A failure of either discards the model output and forces the deterministic template.
"""
from __future__ import annotations

import re

# recommendation / directive / second-person-position vocabulary (case-insensitive)
#
# On "price target": an analyst ISSUING one is a recommendation and stays banned. Merely naming
# the target price a user recorded on their own trade is description, and banning that made the
# chart coach discard correct readings and then report "no vision model connected" — a lie the
# product must not tell. So the rule fires on issuance ("price target of $190", "raised its price
# target"), not on reference ("the distance from entry to the target price"). numbers_guard
# independently stops the model inventing a level, so nothing is lost by narrowing this.
_DIRECTIVE = re.compile(
    r"\byou\s+(should|could|ought|might\s+want|need|must)\b"
    r"|\b(i|we|they|analysts?)\s+(recommend|suggest|advise)\b"
    r"|\brecommend(s|ed)?\s+(buying|selling|holding|adding|trimming|a\s+position|the\s+stock|shares)\b"
    r"|\b(should|must)\s+(buy|sell|hold|add|trim|exit|enter|own|avoid)\b"
    r"|\b(strong\s+buy|strong\s+sell|over\s?weight|under\s?weight|outperform|underperform)\b"
    r"|\b(price\s+target|target\s+price)\s+(of|is|at|to)\s+\$?\d"
    r"|\b(set|sets|setting|raise|raises|raised|lower|lowers|lowered|cut|cuts|issue|issues|"
    r"assign|assigns|reiterate|reiterates)\s+(a|an|the|its|their)?\s*(price\s+target|target\s+price)\b"
    r"|\b(buy|sell)\s+(now|the\s+dip|this|it|shares|the\s+stock)\b"
    r"|\bgo(ing)?\s+(long|short)\b"
    r"|\btake\s+a\s+position\b",
    re.IGNORECASE,
)

_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def directive_guard(text: str) -> bool:
    """True if the text is free of directive/advice language."""
    return _DIRECTIVE.search(text) is None


def _forms(x: float) -> set[str]:
    """String forms a payload number may legitimately appear as in prose: raw, integer,
    1–2 dp, and — for a fraction in [0,1] — its percent forms."""
    out: set[str] = set()
    for v in (x, round(x), round(x, 1), round(x, 2)):
        s = f"{v:.10f}".rstrip("0").rstrip(".")
        out.add(s)
    if 0.0 <= x <= 1.0:
        for pct in (x * 100, round(x * 100), round(x * 100, 1)):
            out.add(f"{pct:.10f}".rstrip("0").rstrip("."))
    return out


def _walk(obj, acc: set[str]) -> None:
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        acc |= _forms(float(obj))
    elif isinstance(obj, str):
        for m in _NUM.findall(obj):  # numbers embedded in strings (dates, iso timestamps)
            try:
                acc |= _forms(float(m.replace(",", "")))
            except ValueError:
                pass
    elif isinstance(obj, dict):
        for v in obj.values():
            _walk(v, acc)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _walk(v, acc)


def allowed_numbers(*payloads) -> set[str]:
    """All numeric strings the model is permitted to mention, drawn from the real payloads
    plus the fixed structural constants (horizons, window, min-sample)."""
    acc: set[str] = set()
    for p in payloads:
        _walk(p, acc)
    for c in (30, 90, 180):  # horizons / window / min episodes are structural, always allowed
        acc |= _forms(float(c))
    return acc


# a stated hit-rate claim, e.g. "68% of the time", "68% hit", "68% success"
_RATE_PHRASE = re.compile(r"(\d+(?:\.\d+)?)\s*%\s*(?:of the time|hit|success|win)", re.IGNORECASE)


def base_rate_integrity_guard(text: str, cal: dict | None) -> bool:
    """The base-rate claim in the output must match the backtest record exactly (Feature Spec
    5.5, decision #33). With no sufficient sample, the output may not state a hit rate at all."""
    claims = [float(m) for m in _RATE_PHRASE.findall(text)]
    if not cal or not cal.get("sufficient"):
        return len(claims) == 0
    allowed = round(cal["hit_rate"] * 100)
    return all(round(c) == allowed for c in claims)


def numbers_guard(text: str, allowed: set[str]) -> bool:
    """True if every number in the text traces to an allowed payload number."""
    for tok in _NUM.findall(text):
        norm = tok.replace(",", "")
        try:
            forms = _forms(float(norm))
        except ValueError:
            continue
        if forms & allowed:
            continue
        if re.fullmatch(r"(19|20)\d\d", norm):  # a plausible year (dates in prose)
            continue
        return False
    return True
