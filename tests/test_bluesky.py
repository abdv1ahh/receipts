"""Offline tests for the Bluesky adapter's parsing and mapping.

Payloads below are real records captured from the live public AppView on 2026-07-26 (trimmed to the
fields the adapter reads). No network here.

Why this source exists at all: the brief asks for X, X has no free read tier, and Appendix A names
Bluesky as the substitute. Its keyless *search* endpoint returns 403 as of the same date, so this
reads a curated account list instead — which is what the brief wanted from a social source anyway.
"""
from datetime import UTC

from tradeos.ingestion import social_bluesky as bsky

ACCOUNT = {"handle": "reuters.com", "display_name": "Reuters", "influence": 0.85,
           "country": None, "domain": "general"}

# Verbatim shape from the live API.
REAL_POST = {
    "post": {
        "uri": "at://did:plc:jbvnehrrdqoulco4rf5gxg5r/app.bsky.feed.post/3mrkltlrk272o",
        "author": {"handle": "reuters.com", "displayName": "Reuters"},
        "record": {
            "text": "Five Bosnian climbers feared dead on Russia's Mount Elbrus reut.rs/3Tbf2Yd",
            "createdAt": "2026-07-26T14:30:38Z",
            "langs": ["en"],
        },
    },
}


# ------------------------------------------------------------------ timestamps

def test_parse_time_reads_the_z_suffixed_iso_bluesky_sends():
    dt = bsky._parse_time("2026-07-26T14:30:38Z")
    assert (dt.year, dt.month, dt.day, dt.hour, dt.minute) == (2026, 7, 26, 14, 30)
    assert dt.tzinfo is not None          # must be aware; it becomes knowable_time
    assert dt.utcoffset().total_seconds() == 0


def test_parse_time_returns_none_rather_than_guessing():
    assert bsky._parse_time(None) is None
    assert bsky._parse_time("") is None
    assert bsky._parse_time("last Tuesday") is None


# ------------------------------------------------------------------ links

def test_post_url_builds_an_openable_link_from_the_at_uri():
    url = bsky.post_url("reuters.com", "at://did:plc:abc/app.bsky.feed.post/3mrkltlrk272o")
    assert url == "https://bsky.app/profile/reuters.com/post/3mrkltlrk272o"


def test_post_url_is_empty_when_it_cannot_be_built():
    # Provenance is mandatory, so an unlinkable post must be droppable rather than stored bare.
    assert bsky.post_url("", "at://x/y/z") == ""
    assert bsky.post_url("reuters.com", "") == ""


# ------------------------------------------------------------------ mapping

def test_to_event_maps_a_real_post():
    ev = bsky.to_event(REAL_POST, ACCOUNT)
    assert ev["source"] == "bluesky"
    assert ev["external_id"].startswith("at://")          # Bluesky's own stable identity
    assert ev["source_url"] == (
        "https://bsky.app/profile/reuters.com/post/3mrkltlrk272o")
    assert ev["title"].startswith("Five Bosnian climbers")
    assert ev["author"] == "Reuters"
    assert ev["author_influence"] == 0.85                 # stated editorial weight from the list
    assert ev["language"] == "en"
    assert ev["published_at"] == ev["knowable_time"]      # a public post is knowable when posted
    assert ev["published_at"].tzinfo is not None
    assert ev["raw_payload"] == REAL_POST                 # kept whole, so the engine can be rerun


def test_to_event_leaves_geo_empty():
    """geo is where an event LANDS, never where the publisher sits.

    This is the single most repeated mistake in this codebase, so it gets a test on every new
    source. A Reuters post is not a UK event.
    """
    assert bsky.to_event(REAL_POST, ACCOUNT)["geo"] == []


def test_to_event_leaves_category_to_the_spine():
    # None means spine.classify reads the text; a source must not assert a category it guessed.
    assert bsky.to_event(REAL_POST, ACCOUNT)["category"] is None


def test_to_event_splits_the_first_line_into_the_title():
    item = {"post": {**REAL_POST["post"],
                     "record": {**REAL_POST["post"]["record"],
                                "text": "Headline goes here\n\nAnd the detail follows."}}}
    ev = bsky.to_event(item, ACCOUNT)
    assert ev["title"] == "Headline goes here"
    assert ev["body"] == "And the detail follows."


def test_to_event_skips_reposts():
    """A repost is the watched account amplifying someone ELSE. Storing it as that account's own
    statement would put words in a central bank's mouth."""
    repost = {**REAL_POST, "reason": {"$type": "app.bsky.feed.defs#reasonRepost"}}
    assert bsky.to_event(repost, ACCOUNT) is None


def test_to_event_drops_anything_missing_what_makes_it_usable():
    for broken in (
        {"post": {**REAL_POST["post"], "record": {**REAL_POST["post"]["record"], "text": "  "}}},
        {"post": {**REAL_POST["post"], "uri": ""}},
        {"post": {**REAL_POST["post"],
                  "record": {**REAL_POST["post"]["record"], "createdAt": "nonsense"}}},
        {},
    ):
        assert bsky.to_event(broken, ACCOUNT) is None


def test_to_event_falls_back_to_the_posts_own_handle():
    """The account row is the label of record, but a post always carries its author, so a row with
    no display_name still produces an attributed event rather than an anonymous one."""
    ev = bsky.to_event(REAL_POST, {"handle": "reuters.com", "influence": 0.85})
    assert ev["author"] == "reuters.com"


def test_title_is_capped_so_one_post_cannot_bloat_a_row():
    long_text = "x" * 900
    item = {"post": {**REAL_POST["post"],
                     "record": {**REAL_POST["post"]["record"], "text": long_text}}}
    assert len(bsky.to_event(item, ACCOUNT)["title"]) <= 300


# ------------------------------------------------------------------ the shape of the source itself

def test_adapter_does_not_reach_for_the_search_endpoint():
    """searchPosts 403s without authentication, so relying on it would be a panel that silently
    stays empty. If someone reintroduces it, this fails and they read the module docstring."""
    src = (bsky.__file__ and open(bsky.__file__, encoding="utf-8").read()) or ""
    assert "searchPosts" not in src.split('"""', 2)[-1]   # allowed in the docstring, not in code


def test_utc_import_is_used_for_awareness():
    # Guards against a refactor that drops tzinfo and silently shifts every knowable_time.
    assert bsky._parse_time("2026-07-26T14:30:38+02:00").astimezone(UTC).hour == 12


def test_the_adapter_checks_the_host_like_every_other_one_here():
    """gdelt, prices and reddit all re-derive the hostname from the URL they are about to request
    and refuse anything off the allowlist. A new adapter that skips it is a quiet deviation from a
    security pattern the package already holds, so this asserts the guard exists."""
    src = open(bsky.__file__, encoding="utf-8").read()
    assert "host allowlist violation" in src
    assert "urlparse(url).hostname != HOST" in src
