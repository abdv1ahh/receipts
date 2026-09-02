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


def score_card_svg(symbol: str, name: str, score: int | None, bucket: str | None, headline: str,
                   brand: str = "Rhumb") -> str:
    """A 1200x630 shareable card: the Smart Money Score, the ticker, the story, and a permanent,
    non-removable honesty footer. Pure string; no dependency. Every value is passed in from real data.

    `brand` is a parameter rather than a literal because this card had the pre-rebrand name welded
    into it as markup — TRADE<tspan>OSS</tspan> — which is exactly the thing CLAUDE.md forbids, and
    it was the most public string in the product: the image a shared link renders in every feed.
    Still pure, so the caller passes config.brand_name() in.
    """
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
  <text x="80" y="90" font-family="Arial, sans-serif" font-size="30" font-weight="800" fill="#5b8cff" letter-spacing="1">{_xml_escape(brand.upper())}</text>
  <text x="80" y="128" font-family="Arial, sans-serif" font-size="20" fill="#7a8699">See what smart money is quietly doing</text>
  <rect x="80" y="200" width="330" height="330" rx="34" fill="{fill}" stroke="{color}" stroke-opacity="0.5"/>
  <text x="245" y="400" font-family="Arial, sans-serif" font-size="170" font-weight="800" fill="{color}" text-anchor="middle">{score_txt}</text>
  <text x="245" y="470" font-family="Arial, sans-serif" font-size="26" fill="{color}" text-anchor="middle" letter-spacing="3">SMART MONEY</text>
  <text x="470" y="250" font-family="Arial, sans-serif" font-size="86" font-weight="800" fill="#ffffff">{_xml_escape(symbol)}</text>
  <text x="470" y="292" font-family="Arial, sans-serif" font-size="26" fill="{color}" font-weight="700">{band_txt}</text>
  <g font-family="Arial, sans-serif">{head_svg}</g>
  <text x="80" y="590" font-family="Arial, sans-serif" font-size="22" fill="#7a8699">Backtested &amp; probability-framed. Not investment advice.</text>
</svg>'''



# ------------------------------------------------------------------ Receipts share card
#
# A different object from the score card above, and it looks different on purpose. That one sells a
# signal; this one is a certificate. Registry typography, tabular figures, generous space, and
# muted verdict colours: a miss is a normal outcome and must not be painted as an alarm, because a
# record that makes its own losses look like emergencies is a record nobody will publish honestly.
#
# THE ONE RULE THIS FUNCTION MUST NEVER BREAK: a gated record shows counts and the words Low N, and
# never a percentage. A share card is the part of this product that travels furthest from its own
# context, so it is the worst possible place to print a rate the sample cannot support.

_RECEIPT_INK = {
    "bg": "#05060c", "panel": "#0e111b", "border": "#1b2130",
    "text": "#eaecf4", "muted": "#8b93ab", "faint": "#7b83a0",
    # Low saturation on purpose. Neon green for a hit and alarm red for a miss would put a thumb on
    # the scale of how a reader feels about a number that is meant to be read, not reacted to.
    "hit": "#7fb69a", "miss": "#c98a95", "accent": "#6e8cff",
}
_SERIF = "Instrument Serif, Iowan Old Style, Georgia, serif"
_MONO = "IBM Plex Mono, ui-monospace, SF Mono, Menlo, Consolas, monospace"
_SANS = "Inter, -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif"


def _count_block(x: int, label: str, value: int, colour: str) -> str:
    return (f'<text x="{x}" y="330" font-family="{_MONO}" font-size="58" font-weight="600" '
            f'fill="{colour}">{value}</text>'
            f'<text x="{x}" y="364" font-family="{_SANS}" font-size="19" fill="{_RECEIPT_INK["faint"]}" '
            f'letter-spacing="1.5">{_xml_escape(label)}</text>')


def receipt_card_svg(handle: str, display_name: str, counts: dict, hit_rate: float | None,
                     hit_rate_ci: list | None, resolved_scoreable: int, links: int,
                     brand: str, verified: bool = False, is_house: bool = False) -> str:
    """The share card for one public record. Pure: every value is passed in from a real query.

    `hit_rate` arriving as None IS the gated case, and it is the only signal this function needs:
    `record.summary` already refuses to return a rate below the sample gate, so a percentage can
    never reach this card without having cleared it upstream.
    """
    ink = _RECEIPT_INK
    gated = hit_rate is None

    if gated:
        headline = (f'<text x="80" y="470" font-family="{_MONO}" font-size="40" fill="{ink["muted"]}" '
                    f'letter-spacing="2">LOW N</text>'
                    f'<text x="230" y="470" font-family="{_SANS}" font-size="23" fill="{ink["faint"]}">'
                    f'{resolved_scoreable} resolved so far. A rate is not shown below 25.</text>')
    else:
        ci = ""
        if hit_rate_ci:
            ci = (f'<text x="330" y="470" font-family="{_MONO}" font-size="25" fill="{ink["faint"]}">'
                  f'95% interval {hit_rate_ci[0]:.1%} to {hit_rate_ci[1]:.1%}</text>')
        headline = (f'<text x="80" y="478" font-family="{_MONO}" font-size="62" font-weight="600" '
                    f'fill="{ink["text"]}">{hit_rate:.1%}</text>'
                    f'<text x="330" y="440" font-family="{_SANS}" font-size="23" fill="{ink["muted"]}">'
                    f'right on {resolved_scoreable} resolved calls</text>{ci}')

    house = ""
    if is_house:
        house = (f'<text x="80" y="212" font-family="{_SANS}" font-size="20" fill="{ink["accent"]}" '
                 f'letter-spacing="1.5">OUR OWN SIGNAL ENGINE</text>')

    mark = "&#10003; verified" if verified else "unverified"
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630">
  <rect width="1200" height="630" fill="{ink["bg"]}"/>
  <rect x="40" y="40" width="1120" height="550" rx="18" fill="{ink["panel"]}" stroke="{ink["border"]}"/>
  <text x="80" y="112" font-family="{_SANS}" font-size="21" font-weight="700" fill="{ink["accent"]}" letter-spacing="3">{_xml_escape(brand.upper())}</text>
  <text x="1120" y="112" font-family="{_SANS}" font-size="19" fill="{ink["faint"]}" text-anchor="end">{mark}</text>
  <line x1="80" y1="140" x2="1120" y2="140" stroke="{ink["border"]}"/>
  {house}
  <text x="80" y="{"268" if is_house else "250"}" font-family="{_SERIF}" font-size="60" fill="{ink["text"]}">{_xml_escape(display_name)}</text>
  <text x="80" y="{"306" if is_house else "288"}" font-family="{_MONO}" font-size="25" fill="{ink["muted"]}">@{_xml_escape(handle)}</text>
  {_count_block(80, "HIT", counts.get("hit", 0), ink["hit"])}
  {_count_block(240, "MISS", counts.get("miss", 0), ink["miss"])}
  {_count_block(400, "INCONCLUSIVE", counts.get("inconclusive", 0), ink["muted"])}
  {_count_block(690, "UNSCOREABLE", counts.get("unscoreable", 0), ink["muted"])}
  {_count_block(960, "OPEN", counts.get("open", 0), ink["muted"])}
  <line x1="80" y1="400" x2="1120" y2="400" stroke="{ink["border"]}"/>
  {headline}
  <text x="1120" y="470" font-family="{_MONO}" font-size="23" fill="{ink["accent"]}" text-anchor="end">{links} sealed calls, chained</text>
  <text x="80" y="548" font-family="{_SANS}" font-size="19" fill="{ink["faint"]}">Past performance does not predict future results. This measures public statements and is not investment advice.</text>
</svg>'''
