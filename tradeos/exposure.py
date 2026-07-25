"""Exposure — what your holdings are actually exposed to.

This replaces the position tracker. A broker already shows you what you own and what it is worth,
does it better, and does it with real prices; building a worse version of that was the honest
criticism of the old Portfolio surface. What no broker shows you is the second question, which is
the one this product is built to answer: *given what I hold, which live events actually reach me,
and through what?*

So Exposure answers four things a position list cannot:

  which live claims touch what you hold, and by what mechanism
  which countries and corridors you depend on, through the companies you own
  where your holdings are concentrated in ways you may not have noticed
  which upcoming calendar entries intersect your names

The honesty rules that shape it:

  * A link is only drawn when it can be explained. "You are exposed to China" is worthless without
    "because two of your holdings have claims naming Asia".
  * Concentration is stated as a fact about your list, never as a warning about your judgement.
    The product does not know your circumstances and does not get to tell you your risk is wrong.
  * Nothing here is advice. It is a description of connections that already exist.
"""
from __future__ import annotations

import logging

from . import geography

log = logging.getLogger("tradeos.exposure")

# Above this share of a holdings list in one bucket, the concentration is worth stating plainly.
# Not a threshold for "too much" — a threshold for "worth pointing out".
NOTABLE_SHARE = 0.34


def concentration(labels: list[str]) -> list[dict]:
    """How a list of holdings distributes across some bucket (sector, country, currency).

    Returns every bucket with its share, flagging the ones large enough to be worth naming. Pure."""
    if not labels:
        return []
    total = len(labels)
    counts: dict[str, int] = {}
    for label in labels:
        if label:
            counts[label] = counts.get(label, 0) + 1
    out = [{"label": k, "count": v, "share": round(v / total, 3), "notable": v / total >= NOTABLE_SHARE}
           for k, v in counts.items()]
    return sorted(out, key=lambda x: -x["count"])


def claims_touching(claims: list[dict], holdings: set[str]) -> list[dict]:
    """Live claims that name something you hold, each with WHICH holding and in which direction.

    A claim reaches you through a specific name; saying "this affects your portfolio" without
    saying which position would be an unfalsifiable statement, which is what this whole product
    exists to avoid. Pure."""
    out = []
    for c in claims:
        hits = [a for a in (c.get("affected") or [])
                if str(a.get("value", "")).upper() in holdings]
        if hits:
            out.append({**c, "your_holdings": [
                {"symbol": str(a["value"]).upper(), "direction": a.get("direction"),
                 "magnitude": a.get("magnitude")} for a in hits]})
    return sorted(out, key=lambda c: -(c.get("confidence") or 0))


def geographic_reach(claims: list[dict], holdings: set[str]) -> list[dict]:
    """Countries you are reachable from, and the holding that carries each link.

    This is the second-order part the brief asks for: not where a company is listed, but which
    parts of the world its live claims implicate. Every entry names the path, so the reader can
    disagree with it."""
    reach: dict[str, dict] = {}
    for c in claims:
        held = [str(a["value"]).upper() for a in (c.get("affected") or [])
                if str(a.get("value", "")).upper() in holdings]
        if not held:
            continue
        for iso in geography.countries_for(c.get("affected") or []):
            entry = reach.setdefault(iso, {"country": iso, "via": [], "claims": 0})
            entry["claims"] += 1
            for symbol in held:
                if symbol not in entry["via"]:
                    entry["via"].append(symbol)
    return sorted(reach.values(), key=lambda r: -r["claims"])


def corridor_dependence(reach: list[dict], corridors: list[dict],
                        home: str | None) -> list[dict]:
    """Trade corridors linking the reader's own country to the places their holdings reach.

    Only drawn when there is a home country to draw them from — a corridor with one end missing is
    a line to nowhere, and the surface says so rather than showing one."""
    if not home:
        return []
    touched = {r["country"] for r in reach}
    out = []
    for k in corridors:
        if k["from"] == home and k["to"] in touched:
            out.append({**k, "role": "you export to"})
        elif k["to"] == home and k["from"] in touched:
            out.append({**k, "role": "you import from"})
    return sorted(out, key=lambda k: -k["weight"])


def upcoming_intersections(events: list[dict], holdings: set[str]) -> list[dict]:
    """Scheduled calendar entries that land on something you hold."""
    return [e for e in events if str(e.get("symbol") or "").upper() in holdings]


def summarise(holdings: list[str], touching: list[dict], reach: list[dict],
              intersections: list[dict]) -> dict:
    """The one-line read at the top of the surface. States what is there; never grades it."""
    exposed = len({h for c in touching for h in
                   [x["symbol"] for x in c.get("your_holdings", [])]})
    return {
        "holdings": len(holdings),
        "with_live_claims": exposed,
        "countries_reached": len(reach),
        "upcoming_events": len(intersections),
        "line": (
            f"{exposed} of your {len(holdings)} holdings "
            f"{'has' if exposed == 1 else 'have'} a live interpretation attached"
            if exposed else
            f"None of your {len(holdings)} holdings has a live interpretation attached right now"
        ),
    }
