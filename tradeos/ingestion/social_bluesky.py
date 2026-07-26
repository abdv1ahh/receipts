"""Bluesky — the social source that is actually open.

The brief asks for X, and X cannot be had: no free read tier, paid tiers far beyond free-tier scope,
and scraping is both against their terms and permanently brittle. Appendix A of the brief names the
alternative, and this is it. Bluesky's AppView answers unauthenticated reads over plain HTTPS, so
consequential accounts that publish there are readable at no cost and with no key.

What was measured against the live API on 2026-07-26, because the situation has changed and the
documentation has not caught up:

  * `app.bsky.actor.getProfile`   → 200, keyless. Resolves a handle to a DID.
  * `app.bsky.feed.getAuthorFeed` → 200, keyless. A named account's posts.
  * `app.bsky.feed.searchPosts`   → **403**. Search now requires authentication.

That last line decides the whole shape of this module. Keyword search across the network is closed,
so this does NOT crawl Bluesky for mentions of a ticker. It reads a curated list of accounts —
which is what the brief asked for anyway ("a curated watchlist of consequential accounts, seeded
manually and editable by the owner"), and which is the better signal regardless: a central banker
posting beats a thousand anonymous accounts saying the same word.

The accounts live in `watchlist_accounts` with `platform = 'bluesky'`, alongside the RSS channels
already there, so the owner edits one list through one management API. `author_influence` on each
event comes from that row's stated editorial weight — a stated weight, never a measurement, and
labelled that way wherever it surfaces.

Posts go through `spine.ingest_events` like every other source, so they cluster, score and reach
the Radar on identical terms. Nothing here is fabricated: when the account list is empty or the
API is unreachable, this returns zero events and says so.
"""
from __future__ import annotations

import logging
import time
from datetime import UTC, datetime

import httpx

from .. import spine

log = logging.getLogger("tradeos.ingestion.bluesky")

HOST = "public.api.bsky.app"
API = "https://public.api.bsky.app/xrpc"
UA = {"User-Agent": "Rhumb/1.0 (world-event research; contact via the application)"}

# The AppView is generous but not free of limits, and this product's whole posture toward free APIs
# is to stay comfortably inside them rather than discover the ceiling. One request per account per
# pass, paced, and a small list.
MIN_INTERVAL_S = 1.2
MAX_POSTS_PER_ACCOUNT = 25
_last_call = 0.0


def _pace() -> None:
    """Space requests out. Module-level rather than per-client because the limit is per-caller."""
    global _last_call
    wait = MIN_INTERVAL_S - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()


# ------------------------------------------------------------------ pure: normalisation

def _parse_time(value: str | None) -> datetime | None:
    """Bluesky timestamps are ISO-8601, usually with a trailing Z and sometimes with microseconds."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def post_url(handle: str, uri: str) -> str:
    """A human-openable link. `uri` is an at:// URI whose last segment is the record key; the web
    app addresses the same post as /profile/<handle>/post/<rkey>. Provenance is not optional here,
    so a post that cannot be linked is not stored."""
    rkey = (uri or "").rsplit("/", 1)[-1]
    return f"https://bsky.app/profile/{handle}/post/{rkey}" if rkey and handle else ""


def to_event(item: dict, account: dict) -> dict | None:
    """One post as a spine event, or None if it lacks what makes it usable.

    Reposts are skipped. A repost is the watched account amplifying someone else, which is a
    different claim about the world from the account saying it, and treating the two as identical
    would put words in a central bank's mouth.
    """
    if item.get("reason"):                       # a repost, not a post by this account
        return None
    post = item.get("post") or {}
    record = post.get("record") or {}
    text = (record.get("text") or "").strip()
    uri = post.get("uri") or ""
    created = _parse_time(record.get("createdAt"))
    author = post.get("author") or {}
    handle = author.get("handle") or account.get("handle") or ""
    url = post_url(handle, uri)
    if not text or not uri or created is None or not url:
        return None

    # The post IS the headline. Bluesky's 300-character limit means the first line is usually the
    # whole point, so the title is the first line and the body keeps the rest.
    first, _, rest = text.partition("\n")
    return {
        "source": "bluesky",
        "external_id": uri,                      # at:// URI — stable, unique, Bluesky's own identity
        "source_url": url,
        "author": account.get("display_name") or handle,
        # A stated editorial weight from the watchlist row, not a measurement of reach.
        "author_influence": account.get("influence"),
        "published_at": created,
        "knowable_time": created,                # a public post is knowable the moment it is posted
        "title": first.strip()[:300] or text[:300],
        "body": rest.strip() or None,
        "language": (record.get("langs") or [None])[0],
        # Deliberately NOT the account's country. `geo` means where an event LANDS, and a Fed
        # statement is not a US-only event. Geography is derived downstream from what a claim
        # affects; guessing it from the publisher is the single most repeated mistake in this
        # codebase and it is not repeated here.
        "geo": [],
        "category": None,                        # spine.classify reads the text and decides
        "raw_payload": item,                     # kept whole, so the engine can be rerun over history
    }


# ------------------------------------------------------------------ network

def _get(client: httpx.Client, method: str, params: dict) -> dict:
    _pace()
    r = client.get(f"{API}/{method}", params=params)
    r.raise_for_status()
    return r.json()


def resolve_did(client: httpx.Client, handle: str) -> str | None:
    """Handle → DID. A DID survives a handle change, which is exactly the sort of silent breakage
    that leaves a panel empty for weeks."""
    try:
        return (_get(client, "app.bsky.actor.getProfile", {"actor": handle}) or {}).get("did")
    except Exception as exc:
        log.warning("bluesky: could not resolve %s (%s)", handle, type(exc).__name__)
        return None


def accounts(conn) -> list[dict]:
    """The active Bluesky rows from the consequential-accounts watchlist."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT handle, display_name, influence, country, domain
                 FROM watchlist_accounts
                WHERE platform = 'bluesky' AND active
                ORDER BY influence DESC, handle""")
        return [{"handle": h, "display_name": d, "influence": i, "country": c, "domain": dom}
                for h, d, i, c, dom in cur.fetchall()]


def ingest(conn, limit: int = MAX_POSTS_PER_ACCOUNT) -> dict:
    """Read every watched Bluesky account and push their posts through the spine.

    One account failing never stops the pass — an account can be renamed, deactivated or deleted at
    any time, and losing the other twenty because of it would be absurd."""
    out: dict = {"events": 0, "clusters": 0, "accounts": 0, "failed": 0}
    watched = accounts(conn)
    if not watched:
        out["skipped"] = "no bluesky accounts in watchlist_accounts"
        log.info("bluesky: %s", out["skipped"])
        return out

    with httpx.Client(timeout=30.0, headers=UA, follow_redirects=True) as client:
        for account in watched:
            try:
                data = _get(client, "app.bsky.feed.getAuthorFeed",
                            {"actor": account["handle"], "limit": limit, "filter": "posts_no_replies"})
            except Exception as exc:
                # A 400 here is usually a handle that no longer exists; log which one, so the owner
                # can fix the row rather than wonder why the panel is thin.
                log.warning("bluesky: %s failed (%s)", account["handle"], type(exc).__name__)
                out["failed"] += 1
                continue
            out["accounts"] += 1
            events = [e for e in (to_event(i, account) for i in (data.get("feed") or [])) if e]
            res = spine.ingest_events(conn, events)
            out["events"] += res["events"]
            out["clusters"] += res["clusters"]
    return out
