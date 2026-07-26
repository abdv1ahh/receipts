"""The event spine: one normalised shape for everything the product ingests, one place that
decides which arrivals are the same happening, and one honest measure of how new each one is.

Three jobs, deliberately kept boring:

  normalise   every source's payload becomes an `events` row. Adapters own the source-specific
              part; this module owns the shape and the write.
  cluster     twenty reports of one happening become one cluster with twenty sources attached.
              Trigram similarity over titles inside a time window, plus shared entities. NOT
              embeddings: those need an inference provider, and a spine that stops ingesting when
              model quota runs out is a worse spine. An embedding pass can refine this later
              without changing anything downstream.
  score       novelty (how much NEW information, not how recent) and amplification (how hard and
              how fast it is spreading), stored with the curve so the interface can say
              "accelerating" or "fading" rather than showing a number that hides direction.

Everything here is pure where it can be, so the whole engine is testable against stored payloads
with no network — which is also what makes reprocessing history possible.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta

from psycopg.types.json import Json

log = logging.getLogger("tradeos.spine")

# Two titles this similar, inside the window, are the same happening on title evidence alone.
SIMILARITY = 0.55

# Below that, a match needs corroboration. Measured across outlets on real data:
#
#   0.54  BBC "Four Palestinians and two Israelis killed"
#         Al Jazeera "Funerals held for four Palestinians killed"        -> SAME event
#   0.42  Al Jazeera "India's 'Cockroach' youth call off protest"
#         BBC "Protesters celebrate resignation of India's..."           -> SAME event
#   0.33  CNBC "Amazon cuts some jobs in its artificial general..."
#         BBC "AI is 'not smart' so what's next in artificial..."        -> DIFFERENT events
#
# Different outlets genuinely word the same story differently, so a threshold low enough to catch
# them also catches unrelated stories that share vocabulary. Title similarity alone cannot separate
# those, which is what the brief was pointing at when it suggested embeddings.
#
# The corroborator is SHARED DISTINCTIVE WORDS. Geography was tried first and is provably the wrong
# signal: `geo` holds where the OUTLET sits, so BBC (GB) and Al Jazeera (QA) covering one story
# never overlap — the same outlet-versus-subject distinction already documented in the GDELT
# adapter, made again here. Proper nouns are what two reports of one event actually share
# ("Palestinians", "Israelis"), and what two unrelated ones do not.
WEAK_SIMILARITY = 0.32
MIN_SHARED_WORDS = 1            # one shared proper noun is meaningful; see distinctive_words
CLUSTER_WINDOW_HOURS = 36        # how far back to look for an existing cluster to join
NOVELTY_WINDOW_HOURS = 48        # the brief's "how new is this relative to the last 48 hours"

CATEGORIES = (
    "monetary_policy", "conflict", "election", "regulation", "supply_chain", "earnings",
    "disaster", "protocol_upgrade", "trade_policy", "energy", "labour", "corporate", "macro",
    "markets", "technology", "health", "other",
)

# Deliberately a lookup table, not a classifier. It runs on every ingested item, it must never
# depend on a model being up, and it is trivially auditable when it gets something wrong. The
# model's job (Phase 3) is reasoning about mechanism, not tagging.
_CATEGORY_CUES: list[tuple[str, tuple[str, ...]]] = [
    # "fed" only in unambiguous phrases — the bare word appears in "fed up", "fed into", "fed by".
    ("monetary_policy", ("interest rate", "rate cut", "rate hike", "rate decision", "central bank",
                         "federal reserve", "fomc", "ecb", "bank of england", "monetary policy",
                         "quantitative", "inflation target", "basis points", "the fed",
                         "fed watchers", "fed officials", "fed chair", "rate-setting")),
    ("conflict", ("airstrike", "invasion", "ceasefire", "militant", "missile", "troops",
                  "war", "insurgen", "shelling", "drone strike")),
    ("election", ("election", "referendum", "ballot", "voters", "parliamentary vote", "poll closes")),
    ("regulation", ("regulator", "antitrust", "lawsuit", "sanction", "ban on", "compliance order",
                    "sec charges", "investigation into", "fined")),
    # Cues are word-bounded, so no cue may carry padding whitespace — "port " compiled to a
    # pattern that could never match. Also note ordering: a dock strike hits supply_chain before
    # labour, which is the reading this product wants.
    ("supply_chain", ("shipping", "port", "ports", "canal", "strait", "freight", "supply chain",
                      "export ban", "shortage", "blockade", "logistics", "dockworkers")),
    ("earnings", ("earnings", "quarterly results", "reported results", "guidance", "profit warning",
                  "revenue rose", "revenue fell")),
    ("disaster", ("earthquake", "hurricane", "typhoon", "flood", "wildfire", "eruption", "tsunami")),
    ("protocol_upgrade", ("hard fork", "mainnet", "protocol upgrade", "testnet", "halving")),
    ("trade_policy", ("tariff", "trade deal", "trade war", "import duty", "wto", "quota on")),
    ("energy", ("opec", "crude", "barrel", "natural gas", "pipeline", "refinery", "lng")),
    ("labour", ("strike", "walkout", "union", "layoffs", "job cuts", "unemployment")),
    ("health", ("outbreak", "pandemic", "vaccine", "who declares", "epidemic")),
    ("technology", ("chip", "semiconductor", "artificial intelligence", "ai", "data centre",
                    "data center", "cloud computing")),
]


# Cues are matched on WORD BOUNDARIES, not as substrings. Plain `in` tagged a story about Fed
# governor Kevin *Warsh* as `conflict`, because "war" is inside "Warsh" — and equally would have
# matched "warehouse", "warning" and "software". Multi-word cues still match across the phrase.
_CUE_PATTERNS: list[tuple[str, re.Pattern[str]]] = []


def _compile_cues() -> None:
    for category, cues in _CATEGORY_CUES:
        alternation = "|".join(re.escape(c) for c in cues)
        _CUE_PATTERNS.append((category, re.compile(rf"\b(?:{alternation})\b", re.IGNORECASE)))


def classify(title: str, body: str | None = None) -> str:
    """The event's category from an explicit cue table. First match wins, and the table is ordered
    most-specific first. Returns 'other' rather than guessing."""
    if not _CUE_PATTERNS:
        _compile_cues()
    text = f"{title or ''} {body or ''}"
    for category, pattern in _CUE_PATTERNS:
        if pattern.search(text):
            return category
    return "other"


# ------------------------------------------------------------------ normalisation

_WS = re.compile(r"\s+")


def normalise_title(title: str) -> str:
    """Titles as compared for similarity: collapsed whitespace, no outlet suffix, no wire prefix.
    Without this, 'Fed holds rates - Reuters' and 'UPDATE 2-Fed holds rates' never match."""
    t = (title or "").strip()
    t = re.sub(r"^(UPDATE|EXCLUSIVE|BREAKING|WRAPUP|REFILE|CORRECTED)[\s\d-]*[-:]\s*", "", t, flags=re.I)
    t = re.sub(r"\s*[|\-–—]\s*[A-Z][\w .&']{2,30}$", "", t)      # trailing " | Reuters", " - CNBC"
    return _WS.sub(" ", t).strip()


def upsert_event(conn, ev: dict) -> int | None:
    """Write one normalised event, idempotent on (source, external_id). Returns its id.

    `ev` is what an adapter produces: source, external_id, source_url, title, knowable_time, and
    optionally published_at, body, language, author, author_influence, entities, geo, category,
    raw_payload. The raw payload is always kept, because that is what makes reprocessing possible.

    `author_influence` is a STATED EDITORIAL WEIGHT supplied by the adapter from the
    consequential-accounts list — never a measurement of reach. It went unwritten until Bluesky
    became the first source that actually supplies one, even though watchlist_accounts.py has always
    described this as the place it is stored."""
    if not ev.get("title") or not ev.get("knowable_time"):
        return None                                  # never store a shapeless row
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO events (source, external_id, source_url, author, author_influence,
                                   published_at, knowable_time, title, body, language, entities,
                                   geo, category, raw_payload)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (source, external_id) DO UPDATE SET
                   title = EXCLUDED.title, body = EXCLUDED.body, geo = EXCLUDED.geo,
                   entities = EXCLUDED.entities, category = EXCLUDED.category,
                   author_influence = EXCLUDED.author_influence,
                   raw_payload = EXCLUDED.raw_payload
               RETURNING id""",
            (ev["source"], str(ev["external_id"])[:400], ev.get("source_url") or "",
             ev.get("author"), ev.get("author_influence"),
             ev.get("published_at"), ev["knowable_time"],
             ev["title"][:1000], (ev.get("body") or None), ev.get("language"),
             Json(ev.get("entities") or []), ev.get("geo") or [],
             ev.get("category") or classify(ev["title"], ev.get("body")),
             Json(ev.get("raw_payload") or {})))
        return cur.fetchone()[0]


# ------------------------------------------------------------------ clustering

def _entity_values(entities) -> list[str]:
    """The comparable identity of an event: its ticker/company/person values."""
    return sorted({str(e.get("value")).upper() for e in (entities or []) if e.get("value")})


# Words too common to mean anything when two headlines share them.
_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "of", "in", "on", "at", "to", "for", "with", "from",
    "as", "by", "is", "are", "was", "were", "be", "been", "has", "have", "had", "will", "would",
    "says", "said", "after", "before", "over", "into", "amid", "new", "more", "than", "that",
    "this", "it", "its", "his", "her", "their", "they", "we", "you", "what", "why", "how", "who",
    "not", "no", "up", "down", "out", "off", "about", "first", "last", "year", "years", "day",
    "days", "week", "month", "one", "two", "three", "million", "billion", "percent",
    # Common headline openers, which are capitalised for position rather than meaning.
    "four", "five", "here", "these", "those", "when", "where", "which", "some", "many", "most",
    "just", "now", "still", "again", "inside", "behind", "could", "should", "might", "may",
}
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]{3,}")


def distinctive_words(title: str) -> set[str]:
    """The words in a headline that identify WHICH event it is: proper nouns. Pure.

    Trigram similarity compares character shape; this compares subject. Measured on the real pairs
    that motivated it:

      BBC "Four Palestinians and two Israelis killed" vs
      Al Jazeera "Funerals held for four Palestinians killed"
        -> shares {palestinians}                        SAME event

      CNBC "Amazon cuts some jobs in its artificial general intelligence unit" vs
      BBC "AI is 'not smart' so what's next in artificial intelligence"
        -> shares nothing; "artificial intelligence" is lowercase common vocabulary,
           and "Amazon" appears in only one                DIFFERENT events

    A plain word count could not separate those — both pairs share two or three words. Requiring
    the shared words to be CAPITALISED MID-HEADLINE keeps proper nouns (who and where) and drops
    topic vocabulary, which is exactly the distinction that matters."""
    proper = set()
    for raw in (title.split() if title else []):
        token = raw.strip("\u201c\u201d\"'.,:;!?()[]")
        # Possessives: "India's" and "India" are the same subject. Stripping them was needed for a
        # real pair — a headline leading "India's ... protest" and another ending "... of India's
        # minister" are the same story.
        token = re.sub(r"'s$", "", token)
        if len(token) < 4 or not token[0].isupper() or not _WORD_RE.fullmatch(token):
            continue
        lowered = token.lower()
        # The first word is capitalised by convention, so it is NOT skipped outright — headlines
        # very often lead with the proper noun that identifies the story. The stopword list is what
        # removes "The", "New", "Why" and friends.
        if lowered not in _STOPWORDS:
            proper.add(lowered)
    return proper


def find_cluster(conn, event_id: int, weak: bool = False) -> int | None:
    """The existing cluster this event belongs to, or None.

    A match needs a time window AND title similarity AND — when both sides name entities — at
    least one entity in common.

    That last condition is not belt-and-braces, it is the whole difference between a spine and a
    mess. SEC filing headlines are templated: "<Company>: reported results of operations". Trigram
    similarity on those matches the TEMPLATE, so without an entity check the first backfill merged
    eight different companies' 8-K filings into one "story". Requiring shared entities separates
    them, while a wire story that names no ticker still falls through to pure title similarity —
    which is what lets a CNBC piece and a GDELT piece about the same tariff cluster together."""
    with conn.cursor() as cur:
        cur.execute("SELECT title, knowable_time, category, entities FROM events WHERE id = %s",
                    (event_id,))
        row = cur.fetchone()
        if not row:
            return None
        title, knowable, category, entities = row
        mine = _entity_values(entities)
        cur.execute(
            """SELECT c.id, similarity(c.title, %s) AS sim, c.title
                 FROM event_clusters c
                WHERE c.last_seen >= %s
                  -- Same category, or either side is uncategorised. The explicit ::text casts are
                  -- required: Postgres cannot infer a bare parameter's type inside IS NULL.
                  AND (c.category IS NOT DISTINCT FROM %s::text
                       OR c.category IS NULL OR %s::text IS NULL)
                  -- Strong title match on its own, or a weaker one left to the caller to
                  -- corroborate by shared distinctive words (see WEAK_SIMILARITY).
                  AND similarity(c.title, %s) >= %s
                  -- When this event names entities, the cluster must already contain one of them,
                  -- unless the cluster names none at all (an unattributed wire story).
                  AND (cardinality(%s::text[]) = 0
                       OR NOT EXISTS (SELECT 1 FROM events m
                                       WHERE m.cluster_id = c.id
                                         AND jsonb_array_length(m.entities) > 0)
                       OR EXISTS (SELECT 1 FROM events m,
                                       jsonb_array_elements(m.entities) AS je
                                   WHERE m.cluster_id = c.id
                                     AND upper(je->>'value') = ANY(%s::text[])))
             ORDER BY sim DESC
                LIMIT 8""",
            (normalise_title(title), knowable - timedelta(hours=CLUSTER_WINDOW_HOURS),
             category, category, normalise_title(title),
             SIMILARITY if not weak else WEAK_SIMILARITY,
             mine, mine))
        candidates = cur.fetchall()
    if not candidates:
        return None
    if not weak:
        return candidates[0][0]
    # In the weak band, require shared distinctive words before merging.
    my_words = distinctive_words(title)
    for cid, _sim, cand_title in candidates:
        if len(my_words & distinctive_words(cand_title)) >= MIN_SHARED_WORDS:
            return cid
    return None


def assign_cluster(conn, event_id: int) -> int:
    """Strong title match first; if none, retry in the weak band with word corroboration."""
    """Put an event in a cluster — joining the one it matches, or forming a new one. Returns the
    cluster id. Recomputes the cluster's aggregates from its members rather than incrementing
    counters, so a reprocess produces the same answer as a live run."""
    cluster_id = find_cluster(conn, event_id) or find_cluster(conn, event_id, weak=True)
    with conn.cursor() as cur:
        if cluster_id is None:
            cur.execute(
                """INSERT INTO event_clusters (canonical_event, title, category, geo,
                                               first_seen, last_seen, source_count, event_count)
                   SELECT id, %s, category, geo, knowable_time, knowable_time, 1, 1
                     FROM events WHERE id = %s
                   RETURNING id""",
                (normalise_title(_title_of(cur, event_id) or ""), event_id))
            cluster_id = cur.fetchone()[0]
        cur.execute("UPDATE events SET cluster_id = %s WHERE id = %s", (cluster_id, event_id))
        _refresh_cluster(cur, cluster_id)
    return cluster_id


def _title_of(cur, event_id: int) -> str | None:
    cur.execute("SELECT title FROM events WHERE id = %s", (event_id,))
    r = cur.fetchone()
    return r[0] if r else None


def _refresh_cluster(cur, cluster_id: int) -> None:
    """Recompute a cluster's aggregates from its members. `source_count` counts DISTINCT sources,
    because ten rewrites from one wire are corroboration by one source, not ten.

    `category` is re-derived too, as the most common one among members. Without that, a cluster
    keeps whatever category its first member happened to have — so improving the classifier and
    reprocessing produced a SECOND cluster for the same story (the reclassified events no longer
    matched their own cluster's stale category) instead of correcting the first."""
    cur.execute(
        """UPDATE event_clusters c SET
               first_seen   = m.first_seen,
               last_seen    = m.last_seen,
               source_count = m.source_count,
               event_count  = m.event_count,
               geo          = m.geo,
               category     = coalesce(m.category, c.category),
               updated_at   = now()
          FROM (SELECT min(knowable_time) AS first_seen, max(knowable_time) AS last_seen,
                       count(DISTINCT source) AS source_count, count(*) AS event_count,
                       coalesce(array_agg(DISTINCT g) FILTER (WHERE g IS NOT NULL), '{}') AS geo,
                       (SELECT category FROM events x WHERE x.cluster_id = %s AND category IS NOT NULL
                         GROUP BY category ORDER BY count(*) DESC, category LIMIT 1) AS category
                  FROM events e LEFT JOIN LATERAL unnest(e.geo) AS g ON true
                 WHERE e.cluster_id = %s) m
         WHERE c.id = %s""",
        (cluster_id, cluster_id, cluster_id))


# ------------------------------------------------------------------ novelty + velocity

def novelty(source_count: int, event_count: int, age_hours: float,
            prior_similar: int) -> float:
    """0..1 — how much NEW information this carries, not how recent it is.

    The brief's example: a story appearing across many sources within an hour after being absent
    for a week matters; the tenth rewrite does not. So corroboration raises it, repetition without
    new sources lowers it, and an existing run of similar coverage in the novelty window lowers it
    hard. Pure."""
    if event_count <= 0:
        return 0.0
    corroboration = min(1.0, source_count / 5.0)             # 5 independent sources saturates
    repetition = source_count / max(event_count, 1)          # 1.0 = every report is a new source
    freshness = max(0.0, 1.0 - (age_hours / NOVELTY_WINDOW_HOURS))
    familiarity = 1.0 / (1.0 + prior_similar)                # a running story is less novel
    return round(min(1.0, corroboration * 0.4 + repetition * 0.2
                     + freshness * 0.2 + familiarity * 0.2), 4)


def amplification(curve: list[dict]) -> float:
    """0..1 — how hard and how fast this is spreading, from the stored velocity curve.

    Uses the RATE of arrival, not the total, so a story that collected fifty reports over a week
    does not outrank one collecting ten in an hour."""
    if len(curve) < 2:
        return 0.0
    recent, prior = curve[-1], curve[-2]
    dt = max(0.25, (_ts(recent["at"]) - _ts(prior["at"])).total_seconds() / 3600.0)
    rate = (recent["events"] - prior["events"]) / dt         # reports per hour, now
    breadth = min(1.0, recent.get("sources", 1) / 8.0)
    return round(min(1.0, (min(1.0, rate / 6.0) * 0.65) + (breadth * 0.35)), 4)


def _ts(v) -> datetime:
    return v if isinstance(v, datetime) else datetime.fromisoformat(str(v))


def trend(curve: list[dict]) -> str:
    """'accelerating' | 'steady' | 'fading' — the direction the interface actually shows. A single
    amplification number hides which way a story is moving, which is the useful part."""
    if len(curve) < 3:
        return "steady"
    a, b, c = curve[-3]["events"], curve[-2]["events"], curve[-1]["events"]
    now_rate, prev_rate = c - b, b - a
    if now_rate > prev_rate and now_rate > 0:
        return "accelerating"
    if now_rate < prev_rate:
        return "fading"
    return "steady"


def score_cluster(conn, cluster_id: int) -> dict:
    """Append the current point to a cluster's velocity curve, then recompute its scores. Called
    after ingestion; safe to call repeatedly (a reprocess replays the same arithmetic)."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT c.source_count, c.event_count, c.first_seen, c.last_seen, c.velocity_curve,
                      c.title, c.category,
                      (SELECT count(*) FROM event_clusters o
                        WHERE o.id <> c.id
                          AND o.last_seen BETWEEN c.first_seen - interval '48 hours' AND c.first_seen
                          AND similarity(o.title, c.title) >= %s) AS prior_similar
                 FROM event_clusters c WHERE c.id = %s""",
            (SIMILARITY, cluster_id))
        row = cur.fetchone()
        if not row:
            return {}
        source_count, event_count, first_seen, last_seen, curve, _title, _cat, prior_similar = row
        curve = list(curve or [])
        point = {"at": last_seen.isoformat(), "events": event_count, "sources": source_count}
        if not curve or curve[-1]["at"] != point["at"]:
            curve.append(point)
        curve = curve[-48:]                                  # bounded; the shape is what matters

        age_h = (last_seen - first_seen).total_seconds() / 3600.0
        nov = novelty(source_count, event_count, age_h, prior_similar or 0)
        amp = amplification(curve)
        cur.execute("UPDATE event_clusters SET novelty_score=%s, amplification=%s, "
                    "velocity_curve=%s, updated_at=now() WHERE id=%s",
                    (nov, amp, Json(curve), cluster_id))
        cur.execute("UPDATE events SET novelty_score=%s, amplification=%s WHERE cluster_id=%s",
                    (nov, amp, cluster_id))
    return {"cluster_id": cluster_id, "novelty": nov, "amplification": amp, "trend": trend(curve)}


def ingest_events(conn, events: list[dict]) -> dict:
    """Normalise, store, cluster and score a batch. The one entry point every adapter uses, so
    every source gets identical treatment and there is one place to change that treatment."""
    written, clusters = 0, set()
    for ev in events:
        eid = upsert_event(conn, ev)
        if eid is None:
            continue
        written += 1
        clusters.add(assign_cluster(conn, eid))
    conn.commit()
    for cid in clusters:
        score_cluster(conn, cid)
    conn.commit()
    return {"events": written, "clusters": len(clusters)}
