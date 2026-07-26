"""First-run onboarding: the sixty seconds that make relevance work (Phase 8).

The brief is blunt about why this exists — *"onboarding capturing country, base currency, and
initial watchlist in under a minute, because relevance scoring is worthless without it. Skippable
but gently persistent."*

It was right, and the cost of not having it turned out to be larger than expected. `user_profiles`
and `PUT /api/profile/frame` have existed since Phase 3, and nothing ever asked a new account to
fill them, so almost every profile is empty. Combined with the geo bug found in Phase 7 — relevance
ranking on the publisher's country rather than the subject's — the personalisation the product is
built around was, in practice, off for everyone.

Three rules:

  * **Nothing here gates a feature.** A reader who skips forever gets the whole product; they get
    the unranked-for-them ordering, which the Radar already says out loud. Onboarding that holds a
    product hostage is a conversion tactic, not a setup step.

  * **Every field is optional and every default is stated, never assumed silently.** The currency
    is *proposed* from the country's published row and shown as a proposal, because a reader in
    Singapore may well account in USD and quietly deciding for them is the kind of small wrong
    answer that erodes trust in the large ones.

  * **Only countries with real exposure data are offered.** Ten rows, hand-checked, each with a
    source. Offering a country the product has no figures for would mean accepting a frame it
    cannot actually score against.
"""
from __future__ import annotations

import logging
from datetime import timedelta

import psycopg

log = logging.getLogger("tradeos.onboarding")

SNOOZE = timedelta(days=3)       # how long a skip lasts before the prompt returns
MAX_WATCHLIST = 12               # a starting list, not a portfolio import


def state(conn: psycopg.Connection, user_id: int) -> dict:
    """What, if anything, this reader still needs to be asked.

    `due` is the only field the interface should branch on. It is false for a reader who finished,
    false for one who skipped recently, and true otherwise — so "gently persistent" lives here
    rather than being re-derived by every caller."""
    with conn.cursor() as cur:
        cur.execute("""SELECT country, base_currency, onboarded_at, snoozed_until
                         FROM user_profiles WHERE user_id = %s""", (user_id,))
        row = cur.fetchone()
        cur.execute("SELECT count(*) FROM watchlists WHERE user_id = %s", (user_id,))
        watched = cur.fetchone()[0]
        cur.execute("SELECT now()")
        now = cur.fetchone()[0]

    country, currency, done, snoozed = (row or (None, None, None, None))
    return {
        "due": not done and not (snoozed and snoozed > now),
        "completed": bool(done),
        "country": country,
        "base_currency": currency,
        "watchlist_count": watched,
        # Reported so the interface can say what it is for rather than just asking. A reader who
        # understands that the country changes their feed answers it; one who does not, skips.
        "why": "Your country and currency decide what reaches the top of your Radar. Without them "
               "every reader sees the same ordering, which in practice means the American one.",
    }


def countries(conn: psycopg.Connection) -> list[dict]:
    """The countries that can actually be chosen, with the currency each one proposes."""
    with conn.cursor() as cur:
        cur.execute("""SELECT country, name, currency, main_index, source
                         FROM country_exposure ORDER BY name""")
        return [{"country": r[0], "name": r[1], "currency": r[2], "main_index": r[3], "source": r[4]}
                for r in cur.fetchall()]


def _clean_symbols(symbols) -> list[str]:
    """Uppercase, de-duplicated, length-capped. Not validated against the ticker universe on
    purpose: a reader watching something the product has not resolved yet should still be able to
    say so, and the watchlist surface already reports per-symbol what it can and cannot compute."""
    out: list[str] = []
    for s in symbols or []:
        # `if not s` before str(): str(None) is "NONE", which would silently add a ticker called
        # NONE to a reader's watchlist. Found by the test that checks this function's own output.
        if not s:
            continue
        t = str(s).strip().upper()[:12]
        if t and t not in out:
            out.append(t)
        if len(out) >= MAX_WATCHLIST:
            break
    return out


def complete(conn: psycopg.Connection, user_id: int, country: str | None,
             base_currency: str | None, symbols: list[str] | None) -> dict:
    """Write the frame and the starting watchlist, and mark onboarding done.

    Done means *asked and answered*, including "answered with nothing". A reader who clicks through
    without choosing a country has made a choice, and asking again every session would be the
    nagging the brief explicitly rules out.
    """
    code = (country or "").upper() or None
    if code:
        with conn.cursor() as cur:
            cur.execute("SELECT currency FROM country_exposure WHERE country = %s", (code,))
            row = cur.fetchone()
        if not row:
            return {"error": f"No sourced exposure data for {code}."}
        base_currency = base_currency or row[0]

    picked = _clean_symbols(symbols)
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO user_profiles (user_id, country, base_currency, onboarded_at)
               VALUES (%s, %s, %s, now())
               ON CONFLICT (user_id) DO UPDATE SET
                   country       = COALESCE(EXCLUDED.country, user_profiles.country),
                   base_currency = COALESCE(EXCLUDED.base_currency, user_profiles.base_currency),
                   onboarded_at  = now(),
                   snoozed_until = NULL,
                   updated_at    = now()""",
            (user_id, code, (base_currency or "").upper() or None))
        for sym in picked:
            # Additive. Onboarding seeds a watchlist; it never replaces one, so a reader who
            # somehow reaches this twice does not lose what they already had.
            cur.execute("INSERT INTO watchlists (user_id, symbol) VALUES (%s, %s) "
                        "ON CONFLICT DO NOTHING", (user_id, sym))
    conn.commit()
    return {"saved": True, "country": code, "base_currency": base_currency, "watchlist": picked}


def snooze(conn: psycopg.Connection, user_id: int) -> dict:
    """Dismiss the prompt for a few days. Deliberately not "never": a reader who skips on day one
    has not yet seen the feed they would be personalising, so the question is worth asking once
    more when it means something to them."""
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO user_profiles (user_id, snoozed_until)
               VALUES (%s, now() + %s)
               ON CONFLICT (user_id) DO UPDATE SET snoozed_until = now() + %s, updated_at = now()""",
            (user_id, SNOOZE, SNOOZE))
    conn.commit()
    return {"snoozed_days": SNOOZE.days}
