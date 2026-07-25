"""Personal relevance: why the same event reads differently from Sharjah than from São Paulo.

Relevance combines four things the product already knows:

  confidence   how sure the claim is
  overlap      does it touch something on your watchlist
  geography    does it touch your country, or a country yours depends on through trade
  novelty      is this new information or the tenth rewrite

The country reference data below is deliberately small and hand-curated rather than exhaustive.
The brief says so explicitly, and it is the right call: twenty accurate rows beat two hundred
guessed ones, and every field here is a stated fact with a source rather than an estimate. Add
rows as they are needed; never interpolate one.

Nothing in this module calls a model. Relevance must work when inference is down, because an
unranked feed is useless and a fabricated ranking is worse.
"""
from __future__ import annotations

import logging

log = logging.getLogger("tradeos.relevance")

# Sources: currency regimes from each central bank's own published framework; trade partners from
# UN Comtrade / World Bank country profiles; indices are the benchmark a local reader watches.
# Weighted toward the places this product's early users actually are.
COUNTRIES: list[dict] = [
    {"country": "AE", "name": "United Arab Emirates", "currency": "AED",
     "currency_regime": "pegged_usd", "pegged_to": "USD", "main_index": "ADX General / DFM General",
     "export_partners": ["IN", "SA", "JP", "CN", "IQ"],
     "import_partners": ["CN", "IN", "US", "JP", "DE"],
     "key_exports": ["crude oil", "refined petroleum", "gold", "aluminium"],
     "key_imports": ["gold", "electronics", "machinery", "food"],
     "commodity_exposure": {"oil": "exporter", "gas": "exporter", "gold": "hub",
                            "wheat": "importer", "food": "importer"},
     "source": "UAE Central Bank; UN Comtrade country profile"},
    {"country": "SA", "name": "Saudi Arabia", "currency": "SAR",
     "currency_regime": "pegged_usd", "pegged_to": "USD", "main_index": "Tadawul All Share",
     "export_partners": ["CN", "IN", "JP", "KR", "AE"],
     "import_partners": ["CN", "US", "AE", "IN", "DE"],
     "key_exports": ["crude oil", "petrochemicals"],
     "key_imports": ["machinery", "vehicles", "food"],
     "commodity_exposure": {"oil": "exporter", "gas": "exporter", "wheat": "importer"},
     "source": "SAMA; UN Comtrade"},
    {"country": "US", "name": "United States", "currency": "USD",
     "currency_regime": "floating", "pegged_to": None, "main_index": "S&P 500",
     "export_partners": ["CA", "MX", "CN", "JP", "GB"],
     "import_partners": ["MX", "CN", "CA", "DE", "JP"],
     "key_exports": ["refined petroleum", "aircraft", "semiconductors", "soybeans"],
     "key_imports": ["crude oil", "electronics", "vehicles", "pharmaceuticals"],
     "commodity_exposure": {"oil": "both", "gas": "exporter", "wheat": "exporter"},
     "source": "Federal Reserve; US Census trade data"},
    {"country": "GB", "name": "United Kingdom", "currency": "GBP",
     "currency_regime": "floating", "pegged_to": None, "main_index": "FTSE 100",
     "export_partners": ["US", "DE", "NL", "IE", "FR"],
     "import_partners": ["CN", "DE", "US", "NL", "NO"],
     "key_exports": ["machinery", "cars", "pharmaceuticals", "financial services"],
     "key_imports": ["crude oil", "gas", "vehicles", "food"],
     "commodity_exposure": {"oil": "importer", "gas": "importer", "wheat": "importer"},
     "source": "Bank of England; ONS trade statistics"},
    {"country": "IN", "name": "India", "currency": "INR",
     "currency_regime": "managed", "pegged_to": None, "main_index": "NIFTY 50",
     "export_partners": ["US", "AE", "NL", "CN", "GB"],
     "import_partners": ["CN", "AE", "US", "SA", "RU"],
     "key_exports": ["refined petroleum", "pharmaceuticals", "software services", "gems"],
     "key_imports": ["crude oil", "gold", "electronics", "coal"],
     "commodity_exposure": {"oil": "importer", "gold": "importer", "coal": "importer"},
     "source": "RBI; UN Comtrade"},
    {"country": "CN", "name": "China", "currency": "CNY",
     "currency_regime": "managed", "pegged_to": None, "main_index": "CSI 300",
     "export_partners": ["US", "HK", "JP", "KR", "VN"],
     "import_partners": ["KR", "JP", "TW", "US", "AU"],
     "key_exports": ["electronics", "machinery", "textiles"],
     "key_imports": ["crude oil", "iron ore", "semiconductors", "soybeans"],
     "commodity_exposure": {"oil": "importer", "iron_ore": "importer", "soybeans": "importer"},
     "source": "PBoC; UN Comtrade"},
    {"country": "BR", "name": "Brazil", "currency": "BRL",
     "currency_regime": "floating", "pegged_to": None, "main_index": "Ibovespa",
     "export_partners": ["CN", "US", "AR", "NL", "CL"],
     "import_partners": ["CN", "US", "DE", "AR", "IN"],
     "key_exports": ["soybeans", "iron ore", "crude oil", "beef", "coffee"],
     "key_imports": ["refined petroleum", "machinery", "fertiliser", "electronics"],
     "commodity_exposure": {"oil": "exporter", "soybeans": "exporter", "iron_ore": "exporter",
                            "fertiliser": "importer"},
     "source": "Banco Central do Brasil; UN Comtrade"},
    {"country": "JP", "name": "Japan", "currency": "JPY",
     "currency_regime": "floating", "pegged_to": None, "main_index": "Nikkei 225",
     "export_partners": ["US", "CN", "KR", "TW", "HK"],
     "import_partners": ["CN", "US", "AU", "AE", "SA"],
     "key_exports": ["vehicles", "machinery", "semiconductors"],
     "key_imports": ["crude oil", "LNG", "coal", "food"],
     "commodity_exposure": {"oil": "importer", "gas": "importer", "coal": "importer",
                            "wheat": "importer"},
     "source": "Bank of Japan; UN Comtrade"},
    {"country": "DE", "name": "Germany", "currency": "EUR",
     "currency_regime": "floating", "pegged_to": None, "main_index": "DAX",
     "export_partners": ["US", "FR", "NL", "CN", "PL"],
     "import_partners": ["CN", "NL", "US", "PL", "FR"],
     "key_exports": ["vehicles", "machinery", "chemicals", "pharmaceuticals"],
     "key_imports": ["gas", "crude oil", "electronics", "vehicles"],
     "commodity_exposure": {"gas": "importer", "oil": "importer"},
     "source": "Bundesbank; Destatis"},
    {"country": "SG", "name": "Singapore", "currency": "SGD",
     "currency_regime": "managed", "pegged_to": None, "main_index": "Straits Times Index",
     "export_partners": ["CN", "HK", "MY", "US", "ID"],
     "import_partners": ["CN", "MY", "US", "TW", "JP"],
     "key_exports": ["refined petroleum", "electronics", "chemicals"],
     "key_imports": ["crude oil", "electronics", "food"],
     "commodity_exposure": {"oil": "refiner", "food": "importer"},
     "source": "MAS; Enterprise Singapore"},
]


def seed(conn) -> dict:
    """Load the reference rows. Idempotent, and it updates in place so a corrected figure lands."""
    with conn.cursor() as cur:
        from psycopg.types.json import Json
        for c in COUNTRIES:
            cur.execute(
                """INSERT INTO country_exposure
                       (country, name, currency, currency_regime, pegged_to, main_index,
                        export_partners, import_partners, key_exports, key_imports,
                        commodity_exposure, source)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (country) DO UPDATE SET
                       name=EXCLUDED.name, currency=EXCLUDED.currency,
                       currency_regime=EXCLUDED.currency_regime, pegged_to=EXCLUDED.pegged_to,
                       main_index=EXCLUDED.main_index, export_partners=EXCLUDED.export_partners,
                       import_partners=EXCLUDED.import_partners, key_exports=EXCLUDED.key_exports,
                       key_imports=EXCLUDED.key_imports,
                       commodity_exposure=EXCLUDED.commodity_exposure, source=EXCLUDED.source,
                       updated_at=now()""",
                (c["country"], c["name"], c["currency"], c["currency_regime"], c["pegged_to"],
                 c["main_index"], c["export_partners"], c["import_partners"], c["key_exports"],
                 c["key_imports"], Json(c["commodity_exposure"]), c["source"]))
    conn.commit()
    return {"countries": len(COUNTRIES)}


def geo_weight(profile_country: str | None, exposure: dict | None, event_geo: list[str]) -> float:
    """0..1 — how much a country's reader should care about where this happened.

    Directly about your country is 1.0. A country you trade with matters, and the ORDER matters:
    a top partner more than a fifth one. Everywhere else still scores above zero, because a
    world-event product that only surfaces domestic news is a local newspaper."""
    if not event_geo:
        return 0.3                                   # global/unplaced: mildly relevant to everyone
    if not profile_country:
        return 0.4
    if profile_country in event_geo:
        return 1.0
    if not exposure:
        return 0.3
    # Rank within EACH list, then take the best. Concatenating the two lists offset every import
    # partner by the length of the export list, so a country's largest supplier scored as if it
    # were its sixth-largest customer.
    exports = list(exposure.get("export_partners") or [])
    imports = list(exposure.get("import_partners") or [])
    best = 0.0
    for g in event_geo:
        ranks = [lst.index(g) for lst in (exports, imports) if g in lst]
        if ranks:
            best = max(best, 0.75 - min(min(ranks), 5) * 0.07)   # 0.75 for a top partner, decaying
    return round(best, 3) if best else 0.3


def watchlist_weight(affected: list[dict], watchlist: set[str]) -> float:
    """0..1 — does this claim touch something the user actually holds or follows."""
    if not affected:
        return 0.0
    if not watchlist:
        return 0.35                                  # no watchlist yet: don't zero everything out
    hits = sum(1 for a in affected if str(a.get("value", "")).upper() in watchlist)
    return min(1.0, 0.5 + 0.25 * hits) if hits else 0.15


def currency_weight(exposure: dict | None, affected: list[dict]) -> float:
    """A claim about a currency your own is pegged to is not foreign news — it is your monetary
    policy. This is the sort of second-order link a US-centric feed silently drops."""
    if not exposure or not affected:
        return 0.0
    currencies = {str(a.get("value", "")).upper() for a in affected if a.get("kind") == "currency"}
    if not currencies:
        return 0.0
    if (exposure.get("currency") or "").upper() in currencies:
        return 1.0
    if (exposure.get("pegged_to") or "").upper() in currencies:
        return 0.9                                   # a peg transmits it almost fully
    return 0.2


def score(claim: dict, profile: dict | None, exposure: dict | None,
          watchlist: set[str] | None = None, novelty: float | None = None) -> dict:
    """Relevance 0..1 for one claim and one reader, with the contributing parts returned.

    The parts are returned, not just the total, so the interface can say WHY something is at the
    top of your feed. An unexplained ranking is indistinguishable from an arbitrary one."""
    watchlist = watchlist or set()
    affected = claim.get("affected") or []
    parts = {
        "confidence": float(claim.get("confidence") or 0),
        "watchlist": watchlist_weight(affected, watchlist),
        "geo": geo_weight((profile or {}).get("country"), exposure, claim.get("geo") or []),
        "currency": currency_weight(exposure, affected),
        "novelty": float(novelty if novelty is not None else 0.5),
    }
    total = (parts["confidence"] * 0.25 + parts["watchlist"] * 0.25 + parts["geo"] * 0.25
             + parts["currency"] * 0.10 + parts["novelty"] * 0.15)
    return {"relevance": round(min(1.0, total), 4), "parts": {k: round(v, 3) for k, v in parts.items()}}


# Checked in this order on a tie, most specific reason first: "touches your watchlist" tells a
# reader more than "the interpretation is confident", which is true of most claims.
_REASON_ORDER = ("watchlist", "currency", "geo", "novelty", "confidence")
_LABELS = {"watchlist": "it touches something on your watchlist",
           "currency": "it touches your currency",
           "geo": "of where it happened relative to you",
           "novelty": "it is genuinely new information",
           "confidence": "the interpretation is a confident one"}


def explain(parts: dict) -> str:
    """One plain sentence naming the biggest reason this is in front of you.

    A part scoring zero is never given as a reason — telling a reader an item was shown because it
    "touches your currency" when it names no currency is a small lie, and this product does not
    get to tell small ones."""
    candidates = [k for k in _REASON_ORDER if parts.get(k, 0) > 0]
    if not candidates:
        return "Shown to you as part of the general feed."
    top = max(candidates, key=lambda k: (parts[k], -_REASON_ORDER.index(k)))
    return f"Shown to you because {_LABELS[top]}."
