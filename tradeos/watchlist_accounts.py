"""Consequential accounts: whose statements carry weight, and how much.

A head of state, a central banker, a regulator and an anonymous poster do not carry the same
information. The spine stores `author_influence` on every event that has an author, and this is
where that number comes from.

The brief is explicit that this must be first-class, editable data rather than a hardcoded array,
so it lives in the `watchlist_accounts` table with a management API. The seed below is a starting
point the owner is expected to edit, not a fixed list.

Honesty note on `influence`: it is a stated editorial weight, not a measurement. It says "this
product treats a central bank governor's words as more consequential than an anonymous account",
which is a defensible editorial position — it does not claim to have measured anyone's impact.
Anywhere it reaches the interface it must be labelled that way.
"""
from __future__ import annotations

import logging

from psycopg import sql

log = logging.getLogger("tradeos.watchlist_accounts")

# Seeded from institutions whose statements move markets and whose official channels publish
# through a readable feed. Deliberately institutions and roles rather than personal accounts: an
# institution's feed is stable, and X — where most of the individuals actually post — has no free
# read tier (see sources.py). Handles are the OFFICIAL publishing channel, not a social profile.
SEED: list[dict] = [
    # ---- central banks: the single most consequential category for this product
    {"platform": "rss", "handle": "federalreserve.gov/feeds/press_all.xml",
     "display_name": "US Federal Reserve", "role": "central_bank", "domain": "monetary_policy",
     "country": "US", "influence": 1.0,
     "feed_url": "https://www.federalreserve.gov/feeds/press_all.xml"},
    {"platform": "rss", "handle": "ecb.europa.eu/press/rss",
     "display_name": "European Central Bank", "role": "central_bank", "domain": "monetary_policy",
     "country": "EU", "influence": 0.95,
     "feed_url": "https://www.ecb.europa.eu/rss/press.html"},
    {"platform": "rss", "handle": "bankofengland.co.uk/news/rss",
     "display_name": "Bank of England", "role": "central_bank", "domain": "monetary_policy",
     "country": "GB", "influence": 0.85,
     "feed_url": "https://www.bankofengland.co.uk/news/news.xml"},
    {"platform": "rss", "handle": "boj.or.jp/en/rss",
     "display_name": "Bank of Japan", "role": "central_bank", "domain": "monetary_policy",
     "country": "JP", "influence": 0.85, "feed_url": "https://www.boj.or.jp/en/rss/whatsnew.xml"},

    # ---- regulators
    {"platform": "rss", "handle": "sec.gov/news/pressreleases.rss",
     "display_name": "US SEC", "role": "regulator", "domain": "regulation", "country": "US",
     "influence": 0.8, "feed_url": "https://www.sec.gov/news/pressreleases.rss"},

    # ---- energy and trade bodies
    {"platform": "official", "handle": "opec.org/press",
     "display_name": "OPEC", "role": "cartel", "domain": "energy", "country": None,
     "influence": 0.9, "feed_url": "https://www.opec.org/opec_web/en/press_room/28.htm"},
    {"platform": "official", "handle": "wto.org/news",
     "display_name": "World Trade Organization", "role": "institution", "domain": "trade_policy",
     "country": None, "influence": 0.7, "feed_url": "https://www.wto.org/library/rss/latest_news_e.xml"},
    {"platform": "official", "handle": "imf.org/news",
     "display_name": "IMF", "role": "institution", "domain": "macro", "country": None,
     "influence": 0.75, "feed_url": "https://www.imf.org/en/News/RSS"},
]


def seed(conn) -> dict:
    """Insert the starting set. Idempotent, and it never overwrites an edit the owner has made —
    the whole point of this being data is that they can change it."""
    inserted = 0
    with conn.cursor() as cur:
        for a in SEED:
            cur.execute(
                """INSERT INTO watchlist_accounts
                       (platform, handle, display_name, role, domain, country, influence, feed_url,
                        note)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (platform, handle) DO NOTHING""",
                (a["platform"], a["handle"], a["display_name"], a.get("role"), a.get("domain"),
                 a.get("country"), a.get("influence", 0.5), a.get("feed_url"),
                 "seeded default — edit freely"))
            inserted += cur.rowcount
    conn.commit()
    return {"seeded": inserted, "total": len(SEED)}


def listing(conn, active_only: bool = False) -> list[dict]:
    where = sql.SQL("WHERE active") if active_only else sql.SQL("")
    with conn.cursor() as cur:
        cur.execute(sql.SQL("""SELECT id, platform, handle, display_name, role, domain, country,
                                      influence, feed_url, active, note
                                 FROM watchlist_accounts {where}
                                ORDER BY influence DESC, display_name""").format(where=where))
        cols = ("id", "platform", "handle", "display_name", "role", "domain", "country",
                "influence", "feed_url", "active", "note")
        return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]


def influence_for(conn, author: str | None) -> float | None:
    """The stated weight for an author, or None when they are not on the watchlist. None means
    "unknown", not "zero" — an unlisted author is unrated, and the interface must not imply the
    product has judged them uninfluential."""
    if not author:
        return None
    with conn.cursor() as cur:
        cur.execute("SELECT influence FROM watchlist_accounts WHERE active AND "
                    "(lower(handle) = lower(%s) OR lower(display_name) = lower(%s)) LIMIT 1",
                    (author, author))
        r = cur.fetchone()
    return float(r[0]) if r else None


def upsert(conn, account: dict) -> dict:
    """Create or update one account. The management path; validates the weight is in range rather
    than trusting the caller."""
    influence = float(account.get("influence", 0.5))
    if not 0.0 <= influence <= 1.0:
        return {"error": "influence must be between 0 and 1"}
    if not account.get("platform") or not account.get("handle") or not account.get("display_name"):
        return {"error": "platform, handle and display_name are required"}
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO watchlist_accounts
                   (platform, handle, display_name, role, domain, country, influence, feed_url,
                    active, note)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (platform, handle) DO UPDATE SET
                   display_name = EXCLUDED.display_name, role = EXCLUDED.role,
                   domain = EXCLUDED.domain, country = EXCLUDED.country,
                   influence = EXCLUDED.influence, feed_url = EXCLUDED.feed_url,
                   active = EXCLUDED.active, note = EXCLUDED.note
               RETURNING id""",
            (account["platform"], account["handle"], account["display_name"], account.get("role"),
             account.get("domain"), account.get("country"), influence, account.get("feed_url"),
             bool(account.get("active", True)), account.get("note")))
        return {"id": cur.fetchone()[0]}
