"""Presentation layer: turn a raw convergence cluster into consumer-legible surfaces —
the 0-100 Smart Money Score and a plain-language story of who is converging on a name.

This is DISPLAY ONLY. It never changes the signal or the backtest. convergence.py stays
hash-locked and untouched, so the raw score and the calibrated buckets remain the single
source of truth. The Smart Money Score is a transparent, monotonic re-expression of the raw
score against the very same bucket edges, so the number means what the buckets mean:
  50 = a genuine medium signal begins, 75 = high-conviction begins, 90+ = exceptional/rare.

Everything here is a pure function of already-fetched data (a cluster's contributions plus a
voice->name map), kept apart from any DB access so it is deterministic and offline-testable —
the same discipline the scorer follows. The story states only facts already in the filings
("4 insiders bought"); it never predicts, recommends, or evaluates a user's position. That is
the advice line, and it is not crossed here.
"""
from __future__ import annotations

from .signals.convergence import DEFAULT_PARAMS

_BUCKETS = DEFAULT_PARAMS["buckets"]


def smart_money_score(raw: float, low_max: float | None = None, medium_max: float | None = None) -> int:
    """Map an unbounded raw convergence score to a 0-100 Smart Money Score.

    Piecewise-linear up to the high-conviction edge, then asymptotic toward 100, pinned to the
    real calibrated bucket thresholds:
        raw 0             -> 0
        raw low_max  (3)  -> 50   (medium begins)
        raw medium_max(6) -> 75   (high-conviction begins)
        raw -> infinity   -> 100  (approached slowly; 90+ is genuinely rare)
    Monotonic and continuous. Presentation only; does not affect the signal or calibration.
    """
    lo = _BUCKETS["low_max"] if low_max is None else low_max
    hi = _BUCKETS["medium_max"] if medium_max is None else medium_max
    if raw <= 0:
        return 0
    if raw <= lo:
        v = raw / lo * 50.0
    elif raw <= hi:
        v = 50.0 + (raw - lo) / (hi - lo) * 25.0
    else:
        v = 75.0 + 25.0 * (1.0 - 0.5 ** ((raw - hi) / (hi - lo)))
    return max(0, min(100, round(v)))


# Each scored subtype, in the order it should lead the story, with how to phrase it and the
# human role of the actor behind it. Purely descriptive language — no directives, no forecasts.
_SUBTYPE_STORY = [
    # subtype,            single,                              plural_noun,   verb,                     role
    ("stake_13d_new",    "filed a new 13D activist stake",    "activists",   "filed new 13D stakes",   "Activist"),
    ("stake_13d_amend",  "increased an activist stake",       "activists",   "increased activist stakes", "Activist"),
    ("insider_purchase", "bought on the open market",         "insiders",    "bought on the open market", "Insider"),
    ("stake_13g",        "disclosed a 5%+ stake",             "investors",   "disclosed 5%+ stakes",   "5%+ holder"),
    ("holding_13f",      "opened or added a position",        "funds",       "opened or added positions", "Fund"),
]
_SUBTYPE_INDEX = {s[0]: i for i, s in enumerate(_SUBTYPE_STORY)}


def _voice_ref(voice: str) -> dict:
    """Parse a voice key into a profile reference. 'insider:<cik>' or 'filer:<entity_id>'."""
    kind, _, ident = (voice or "").partition(":")
    if kind == "insider":
        return {"kind": "insider", "id": ident}
    if kind == "filer":
        return {"kind": "institution", "id": int(ident) if ident.isdigit() else ident}
    return {"kind": "unknown", "id": ident}


def cluster_story(contributions: list[dict], names: dict[str, str] | None = None) -> dict:
    """Build the plain-language story of a cluster from its scored contributions.

    Returns {headline, bullets, protagonists}. `names` maps a voice key to a display name;
    when a marquee actor (a named fund/activist) is known it is named, otherwise the count
    speaks ("4 insiders bought"). protagonists are the named actors, most salient first,
    each carrying a profile reference so the UI can link to them.
    """
    names = names or {}
    voices_by_sub: dict[str, list[str]] = {}
    mag_by_voice: dict[str, float] = {}
    seen: dict[str, set[str]] = {}
    for c in contributions:
        sub = c.get("subtype")
        voice = c.get("voice")
        if sub is None or voice is None:
            continue
        if voice not in seen.setdefault(sub, set()):
            seen[sub].add(voice)
            voices_by_sub.setdefault(sub, []).append(voice)
        m = c.get("magnitude")
        if m is not None:
            mag_by_voice[voice] = max(mag_by_voice.get(voice, 0.0), float(m))

    bullets: list[dict] = []
    protagonists: list[dict] = []
    prot_seen: set[str] = set()
    prot_names: set[str] = set()
    for sub, single, plural_noun, verb, role in _SUBTYPE_STORY:
        voices = voices_by_sub.get(sub)
        if not voices:
            continue
        n = len(voices)
        ranked = sorted(voices, key=lambda v: mag_by_voice.get(v, 0.0), reverse=True)
        lead_name = names.get(ranked[0])
        if lead_name and n == 1:
            text = f"{lead_name} {single}"
        elif lead_name and n > 1:
            text = f"{lead_name} + {n - 1} more {verb}"
        else:
            text = f"{n} {plural_noun} {verb}" if n > 1 else f"1 {role.lower()} {single}"
        bullets.append({"text": text, "source_class": _class_of(sub), "count": n})
        for v in ranked:
            nm = names.get(v)
            if nm and v not in prot_seen and nm.lower() not in prot_names:
                prot_seen.add(v)
                prot_names.add(nm.lower())
                protagonists.append({"name": nm, "role": role, **_voice_ref(v)})

    headline = " · ".join(b["text"] for b in bullets[:2])
    return {"headline": headline, "bullets": bullets, "protagonists": protagonists[:6]}


_CLASS_OF = {
    "insider_purchase": "insider", "insider_sale": "insider",
    "stake_13d_new": "activist", "stake_13d_amend": "activist",
    "stake_13g": "passive_stake", "holding_13f": "institutional_holding",
}


def _class_of(subtype: str) -> str:
    return _CLASS_OF.get(subtype, "other")


# ------------------------------------------------------------ shareable score card (SVG)

_BAND_SVG = {"high": ("#33d17a", "#10281c"), "medium": ("#ffb648", "#2a2010"),
             "low": ("#5b8cff", "#141c2e"), None: ("#7a8699", "#151b28")}


def _xml_escape(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _wrap(text: str, width: int, max_lines: int) -> list[str]:
    """Naive word-wrap into at most max_lines of ~width chars, ellipsizing if it overflows."""
    words = (text or "").split()
    lines, cur = [], ""
    for w in words:
        cand = (cur + " " + w).strip()
        if len(cand) <= width:
            cur = cand
        else:
            if cur:
                lines.append(cur)
            cur = w
            if len(lines) >= max_lines:
                break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    lines = lines[:max_lines]
    if lines and " ".join(lines) != " ".join(words):  # we had to drop text -> mark it
        lines[-1] = lines[-1][: width - 1].rstrip() + "…" if len(lines[-1]) >= width - 1 else lines[-1] + " …"
    return lines


def score_card_svg(symbol: str, name: str, score: int | None, bucket: str | None, headline: str) -> str:
    """A 1200x630 shareable card: the Smart Money Score, the ticker, the story, and a permanent,
    non-removable honesty footer. Pure string; no dependency. Every value is passed in from real data."""
    color, fill = _BAND_SVG.get(bucket, _BAND_SVG[None])
    score_txt = str(score) if score is not None else "—"
    band_txt = (bucket or "no active signal").upper()
    lines = _wrap(headline, 42, 2)
    head_svg = "".join(
        f'<text x="470" y="{330 + i * 52}" font-size="34" fill="#d7e0ee">{_xml_escape(ln)}</text>'
        for i, ln in enumerate(lines)
    )
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630">
  <rect width="1200" height="630" fill="#090b11"/>
  <rect width="1200" height="630" fill="url(#g)"/>
  <defs><radialGradient id="g" cx="20%" cy="0%" r="80%">
    <stop offset="0%" stop-color="{color}" stop-opacity="0.12"/><stop offset="60%" stop-color="#090b11" stop-opacity="0"/>
  </radialGradient></defs>
  <text x="80" y="90" font-family="Arial, sans-serif" font-size="30" font-weight="800" fill="#5b8cff" letter-spacing="1">TRADE<tspan fill="#b98cff">OS</tspan></text>
  <text x="80" y="128" font-family="Arial, sans-serif" font-size="20" fill="#7a8699">See what smart money is quietly doing</text>
  <rect x="80" y="200" width="330" height="330" rx="34" fill="{fill}" stroke="{color}" stroke-opacity="0.5"/>
  <text x="245" y="400" font-family="Arial, sans-serif" font-size="170" font-weight="800" fill="{color}" text-anchor="middle">{score_txt}</text>
  <text x="245" y="470" font-family="Arial, sans-serif" font-size="26" fill="{color}" text-anchor="middle" letter-spacing="3">SMART MONEY</text>
  <text x="470" y="250" font-family="Arial, sans-serif" font-size="86" font-weight="800" fill="#ffffff">{_xml_escape(symbol)}</text>
  <text x="470" y="292" font-family="Arial, sans-serif" font-size="26" fill="{color}" font-weight="700">{band_txt}</text>
  <g font-family="Arial, sans-serif">{head_svg}</g>
  <text x="80" y="590" font-family="Arial, sans-serif" font-size="22" fill="#7a8699">Backtested &amp; probability-framed. Not investment advice.</text>
</svg>'''

