"""Crypto, interpreted rather than mirrored.

The old surface showed price, 24h change, market cap and a sparkline. Every number on it was real
and every one was available free elsewhere in five seconds — which is the whole criticism. A
mirror adds nothing.

What this reads instead is **market structure**: who is positioned, how crowded they are, whether
that crowd is building or unwinding, and whether money is entering the system at all. None of that
is visible in a price, and all of it is free.

Three deliberate constraints, from the brief:

**Every reading carries an invalidation condition.** "This reading breaks if the following happens"
is what separates analysis from a horoscope. A reading you cannot be wrong about is worthless, and
this product scores itself, so every reading has to be falsifiable.

**Meme coins are treated as attention and liquidity flow, not fundamentals**, and the base rates
are stated plainly. Pretending otherwise would be the single most expensive lie this product could
tell a reader.

**Nothing is advice.** These are descriptions of positioning that already exists, with the
mechanism spelled out so a reader can disagree.
"""
from __future__ import annotations

import logging

log = logging.getLogger("tradeos.crypto_intel")

# Funding is a spectrum, so the reading is graded rather than binary. A binary threshold was tried
# both ways against live data and was wrong both ways: set low, all five majors read "crowded long"
# simultaneously and the label meant nothing; set high, Bitcoin paying ~6% a year with positioning
# actively building read as "balanced", which throws away the signal.
#
# Bands are in ANNUALISED percent, because that is the only form in which a carry cost is legible.
LEANING_PCT = 2.0             # below this, funding is noise
CROWDED_PCT = 11.0            # a real cost of carry — roughly 0.01% per 8-hour period
EXTREME_PCT = 38.0            # historically hard to sustain; usually resolves with a sharp move

# Retail account share is CORROBORATION, never a trigger on its own.
#
# Measured on live data: every one of the five majors showed 65-74% of accounts long simultaneously,
# including DOGE while its funding was 0.06% a year — which is nothing. Retail perp accounts are
# structurally long almost all of the time, so a 62% long share is the resting state, not a signal.
# An earlier version OR-ed this with funding and consequently labelled all five "crowded long",
# which is a reading that fires on everything and therefore says nothing.
#
# Funding is the primary signal because it is a COST somebody is actually paying, not a survey.
CROWDED_LONG_SHARE = 0.78     # genuinely lopsided, well beyond the structural long bias
CROWDED_SHORT_SHARE = 0.35

# Assets whose moves are driven by attention and reflexive flow rather than cash flows or usage.
# Naming them explicitly is more honest than a blanket "crypto is risky" disclaimer nobody reads.
ATTENTION_DRIVEN = {"DOGE", "SHIB", "PEPE", "BONK", "WIF", "FLOKI", "TRUMP"}


def read_positioning(p: dict) -> dict | None:
    """One asset's positioning, as a falsifiable reading. Pure.

    Returns None when the inputs are too thin to say anything — silence beats a manufactured
    reading, and the surface renders that honestly."""
    funding = p.get("funding_rate")
    if funding is None:
        return None
    ann = p.get("funding_annualised_pct")
    direction = p.get("funding_direction") or "unknown"
    long_share = p.get("long_account_share")
    symbol = p.get("symbol", "")

    # Funding decides; account share only corroborates. See the note on CROWDED_LONG_SHARE.
    magnitude = abs(ann or 0)
    side = "long" if funding > 0 else "short"
    if magnitude < LEANING_PCT:
        band = "balanced"
    elif magnitude < CROWDED_PCT:
        band = f"leaning {side}"
    elif magnitude < EXTREME_PCT:
        band = f"crowded {side}"
    else:
        band = f"extremely crowded {side}"
    extreme = magnitude >= EXTREME_PCT
    lopsided_long = long_share is not None and long_share >= CROWDED_LONG_SHARE
    lopsided_short = long_share is not None and long_share <= CROWDED_SHORT_SHARE

    state = band
    if band == "balanced":
        mechanism = (
            f"Perpetual funding is near zero at about {ann:.1f}% a year, so neither side is paying "
            "meaningfully to hold its position. Leverage is not crowded here, which means a move "
            "would have to come from spot demand rather than from forced liquidations."
        )
        invalidation = ("This reading breaks if funding moves decisively away from zero, which "
                        "would mean leverage is picking a side.")
    elif side == "long":
        strength = "paying up" if magnitude >= CROWDED_PCT else "paying a little"
        mechanism = (
            f"Funding is positive at about {ann:.1f}% a year, so traders holding long positions "
            f"are {strength} — every eight hours — to keep them. Nobody carries a cost unless they "
            "expect a move, so this measures conviction, and above a point it measures crowding. "
            "A crowded long side is what makes a fall violent: the leverage that pushed price up "
            "forces liquidations on the way down."
        )
        invalidation = ("This reading breaks if funding falls back toward zero while open interest "
                        "holds — positions closed calmly rather than forced.")
    else:
        mechanism = (
            f"Funding is negative at about {ann:.1f}% a year, so short holders are paying longs. "
            "Shorts are being compensated to stay, which means the crowd is leaning bearish. The "
            "same crowding logic runs in reverse: a rally forces shorts to buy back, adding to it."
        )
        invalidation = ("This reading breaks if funding turns positive while open interest falls — "
                        "shorts covering into weakness rather than being squeezed.")

    notes = []
    if extreme:
        notes.append("Funding is at a level that is historically hard to sustain; it usually "
                     "resolves through a sharp move rather than by drifting back.")
    if lopsided_long:
        notes.append(f"{long_share:.0%} of accounts are positioned long — lopsided even allowing "
                     "for the fact that retail perp accounts lean long most of the time.")
    elif lopsided_short:
        notes.append(f"Only {long_share:.0%} of accounts are long, which is unusual: retail "
                     "positioning normally leans the other way.")
    if direction == "building":
        notes.append("Positioning is building — the crowd is getting more crowded, not less.")
    elif direction == "unwinding":
        notes.append("Positioning is unwinding — the crowd is thinning out.")
    if symbol in ATTENTION_DRIVEN:
        notes.append("This asset has no cash flows or usage to value it against. Its moves are "
                     "attention and liquidity flow, and positioning data says who is leaning "
                     "which way — not whether anything is worth anything.")

    return {
        "symbol": symbol, "state": state, "mechanism": mechanism,
        "invalidation": invalidation, "notes": notes,
        "funding_annualised_pct": ann, "funding_direction": direction,
        "long_account_share": long_share, "open_interest": p.get("open_interest"),
        "attention_driven": symbol in ATTENTION_DRIVEN,
        "confidence": ("high" if extreme
                       else "medium" if magnitude >= CROWDED_PCT
                       else "low"),
    }


def liquidity(stablecoins: list[dict]) -> dict:
    """Stablecoin supply as a liquidity reading. Pure.

    Stablecoin market cap is the closest free proxy for money sitting inside crypto ready to be
    deployed. Rising supply means capital is entering the system; falling supply means it is
    leaving. It says nothing about direction, and the reading says so."""
    total = sum(float(s.get("market_cap") or 0) for s in stablecoins)
    if not total:
        return {"available": False,
                "note": "No stablecoin supply data in this response, so liquidity is not read."}
    changes = [(s, float(s.get("change_24h") or 0)) for s in stablecoins if s.get("market_cap")]
    weighted = sum(float(s.get("market_cap")) * c for s, c in changes) / total if changes else 0.0
    if weighted > 0.15:
        state, mechanism = "expanding", (
            "Stablecoin supply is growing, which means capital is moving into crypto and sitting "
            "ready rather than leaving. That is fuel, not direction — it says buying power exists, "
            "not that it will be used.")
    elif weighted < -0.15:
        state, mechanism = "contracting", (
            "Stablecoin supply is shrinking, which means capital is leaving the system rather than "
            "rotating inside it. Less standing buying power tends to make moves in either "
            "direction sharper, because there is less to absorb them.")
    else:
        state, mechanism = "flat", (
            "Stablecoin supply is broadly unchanged, so the money already inside crypto is "
            "rotating between assets rather than arriving or leaving.")
    return {"available": True, "state": state, "mechanism": mechanism,
            "total_usd": round(total), "weighted_change_pct": round(weighted, 3),
            "invalidation": ("This reading breaks if supply moves more than a percent in a day, "
                             "which is usually a single issuer minting or redeeming rather than "
                             "broad flows.")}


def structure_summary(readings: list[dict], liq: dict) -> dict:
    """The one-line read at the top. States what the structure is; never says what to do."""
    if not readings:
        return {"line": "No positioning data available right now.", "crowded": 0}
    crowded = [r for r in readings if r["state"] != "balanced"]
    longs = [r for r in crowded if r["state"].endswith("long")]
    shorts = [r for r in crowded if r["state"].endswith("short")]
    if not crowded:
        line = "Leverage is not crowded on either side of the majors right now."
    elif len(longs) > len(shorts):
        strongest = max(longs, key=lambda r: abs(r.get("funding_annualised_pct") or 0))
        line = (f"Leverage is leaning long on {len(longs)} of {len(readings)} majors, most of all "
                f"{strongest['symbol']} at {strongest['funding_annualised_pct']:.1f}% a year.")
    elif shorts:
        strongest = max(shorts, key=lambda r: abs(r.get("funding_annualised_pct") or 0))
        line = (f"Leverage is leaning short on {len(shorts)} of {len(readings)} majors, most of all "
                f"{strongest['symbol']} at {strongest['funding_annualised_pct']:.1f}% a year.")
    else:
        line = f"Positioning is mixed across {len(readings)} majors."
    if liq.get("available"):
        line += f" Stablecoin liquidity is {liq['state']}."
    return {"line": line, "crowded": len(crowded), "long_side": len(longs), "short_side": len(shorts)}


def compose(positioning: dict, stablecoins: list[dict], narrative: list[dict] | None = None) -> dict:
    """The whole interpreted surface."""
    readings = [r for r in (read_positioning(p) for p in positioning.values()) if r]
    readings.sort(key=lambda r: -(abs(r.get("funding_annualised_pct") or 0)))
    liq = liquidity(stablecoins)
    return {
        "summary": structure_summary(readings, liq),
        "positioning": readings,
        "liquidity": liq,
        "narrative": narrative or [],
        "disclaimer": (
            "Positioning describes who is leaning which way and what it costs them to keep "
            "leaning. It is not a forecast and not advice. Every reading carries the condition "
            "that would break it, because a reading you cannot be wrong about is worthless."),
    }
