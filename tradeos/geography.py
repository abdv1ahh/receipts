"""Where events and claims actually land on a map.

The globe is only worth building if the data underneath it is real. Two problems stood between
the spine and a meaningful map, and this module solves both:

**Source country is not event country.** GDELT reports the country of the OUTLET, and the news
adapter marks every US-markets item `US`. A tariff story filed by a US wire about Asian exporters
is not a US event. So geography is derived from what the claim says it AFFECTS — its regions,
currencies and commodities — not from who published it.

**"North America" is not a country.** Claims name regions and currencies because that is how
analysts talk. A globe needs ISO codes, so those are expanded through explicit hand-written maps.

Everything here is a lookup table on purpose. It has to be auditable — a wrong country puts an
event on the wrong part of the world, which is worse than leaving it off — and it must not depend
on a model being up.
"""
from __future__ import annotations

import logging

log = logging.getLogger("tradeos.geography")

# Regions as claims actually name them. Not exhaustive geography: the countries this product can
# say something useful about, which is the set with exposure data behind them.
REGIONS: dict[str, list[str]] = {
    "north america": ["US", "CA", "MX"],
    "south america": ["BR", "AR", "CL", "CO"],
    "latin america": ["BR", "MX", "AR", "CL", "CO"],
    "europe": ["DE", "FR", "GB", "IT", "ES", "NL", "PL", "SE", "CH"],
    "european union": ["DE", "FR", "IT", "ES", "NL", "PL", "SE"],
    "eurozone": ["DE", "FR", "IT", "ES", "NL"],
    "asia": ["CN", "JP", "IN", "KR", "SG", "ID", "TW", "TH", "VN", "MY"],
    "east asia": ["CN", "JP", "KR", "TW"],
    "south asia": ["IN", "PK"],
    "southeast asia": ["SG", "ID", "TH", "VN", "MY"],
    "middle east": ["AE", "SA", "QA", "KW", "IL", "IR", "IQ", "TR"],
    "gulf": ["AE", "SA", "QA", "KW"],
    "gcc": ["AE", "SA", "QA", "KW"],
    "africa": ["NG", "ZA", "EG", "KE"],
    "oceania": ["AU", "NZ"],
    "global": [],          # deliberately empty: "global" places an event nowhere in particular
    "worldwide": [],
    "emerging markets": ["CN", "IN", "BR", "ZA", "MX", "ID", "TR"],
}

# A currency is a claim about the country that issues it, and about anything pegged to it.
CURRENCY_COUNTRIES: dict[str, list[str]] = {
    "USD": ["US"], "EUR": ["DE", "FR", "IT", "ES", "NL"], "GBP": ["GB"], "JPY": ["JP"],
    "CNY": ["CN"], "RMB": ["CN"], "INR": ["IN"], "BRL": ["BR"], "AED": ["AE"], "SAR": ["SA"],
    "CHF": ["CH"], "CAD": ["CA"], "AUD": ["AU"], "KRW": ["KR"], "SGD": ["SG"], "MXN": ["MX"],
    "TRY": ["TR"], "ZAR": ["ZA"], "RUB": ["RU"], "NGN": ["NG"],
}

# Where a commodity claim lands: the producers whose economies move with it. An importer's
# exposure is captured through country_exposure instead — this is about the supply side.
COMMODITY_COUNTRIES: dict[str, list[str]] = {
    "oil": ["SA", "US", "RU", "AE", "IQ", "BR"], "crude": ["SA", "US", "RU", "AE", "IQ", "BR"],
    "brent": ["SA", "AE", "GB"], "wti": ["US"],
    "gas": ["US", "RU", "QA", "AU"], "lng": ["QA", "US", "AU"],
    "wheat": ["US", "RU", "UA", "CA", "AU"], "soybeans": ["BR", "US", "AR"],
    "iron ore": ["AU", "BR"], "copper": ["CL", "PE", "CN"],
    "gold": ["CN", "AU", "RU", "ZA"], "lithium": ["AU", "CL", "CN"],
    "semiconductors": ["TW", "KR", "US", "CN"], "chips": ["TW", "KR", "US", "CN"],
}


def _match(table: dict[str, list[str]], value: str) -> list[str]:
    """Longest-key match, so "south america" is not swallowed by "america"-style prefixes."""
    v = (value or "").strip().lower()
    if not v:
        return []
    if v in table:
        return table[v]
    for key in sorted(table, key=len, reverse=True):
        if key in v:
            return table[key]
    return []


def countries_for(affected: list[dict]) -> list[str]:
    """ISO codes a claim touches, from what it says it affects.

    Deliberately returns [] rather than a guess when nothing maps — an event with no place is
    simply absent from the globe, which is honest. A wrong country is not."""
    out: list[str] = []
    for item in affected or []:
        kind = str(item.get("kind", "")).lower()
        value = str(item.get("value", ""))
        if kind == "region":
            out += _match(REGIONS, value)
        elif kind == "currency":
            out += CURRENCY_COUNTRIES.get(value.strip().upper(), [])
        elif kind == "commodity":
            out += _match(COMMODITY_COUNTRIES, value)
    seen: list[str] = []
    for c in out:
        if c not in seen:
            seen.append(c)
    return seen


def corridors(rows: list[dict]) -> list[dict]:
    """Trade corridors between the countries we hold exposure data for.

    These are real, sourced relationships from `country_exposure`, not generated arcs. `weight`
    encodes partner rank — a top partner draws heavier than a fifth one — because an unweighted
    corridor map is just a hairball. Pure, so it is testable without a database."""
    known = {r["country"] for r in rows}
    out, seen = [], set()
    for row in rows:
        src = row["country"]
        for direction, partners in (("export", row.get("export_partners") or []),
                                    ("import", row.get("import_partners") or [])):
            for rank, dst in enumerate(partners):
                if dst not in known or dst == src:
                    continue          # only draw arcs we can describe from BOTH ends
                key = (src, dst, direction)
                if key in seen:
                    continue
                seen.add(key)
                out.append({"from": src, "to": dst, "direction": direction,
                            "rank": rank + 1, "weight": round(max(0.15, 1.0 - rank * 0.18), 3)})
    return out


def coverage(country_counts: dict[str, int], known_countries: int) -> dict:
    """An honest statement of how much of the world this map can currently speak about.

    The globe must not imply that an empty country is a quiet one. It is far more likely that the
    product simply has no reach there yet, and the interface has to say which."""
    placed = sum(country_counts.values())
    return {
        "countries_with_activity": len(country_counts),
        "countries_with_exposure_data": known_countries,
        "placed_events": placed,
        "note": ("Countries are lit by events this product has actually placed there. An unlit "
                 "country means no coverage yet, not a quiet one — the difference matters, so it "
                 "is stated rather than implied."),
    }
