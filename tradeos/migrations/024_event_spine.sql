-- Migration 024: the event spine (Phase 2).
--
-- Everything the product ingests — a news article, an SEC filing, a social post, a scheduled
-- release — becomes one `events` row. This is the substrate the impact engine (Phase 3) writes
-- claims against, the Radar (Phase 4) ranks, and the globe (Phase 5) draws.
--
-- Why a new table rather than widening news_items: news_items is specifically a US-equity news
-- item keyed by (source, external_id) with a ticker attached, and eleven surfaces read it today.
-- The spine has to hold things that are not news and not about a ticker — a central bank
-- statement, a shipping-lane closure, a post by a head of state. news_items keeps its job as the
-- raw news layer and is ADAPTED into events, so nothing that works today breaks.
--
-- Point-in-time discipline carries over: `knowable_time` is when the information became public,
-- and every ranking and every backtest reads that, never ingested_at.

CREATE TABLE events (
    id              bigserial PRIMARY KEY,
    source          text NOT NULL,              -- 'gdelt' | 'rss/cnbc-top' | 'sec/8-k' | 'bluesky' | ...
    external_id     text NOT NULL,              -- the source's own stable id; makes re-ingest idempotent
    source_url      text NOT NULL,

    author          text,                       -- social/opinion sources; NULL for wire copy
    author_influence real,                      -- 0..1, from watchlist_accounts; NULL when unknown

    published_at    timestamptz,                -- when the source says it happened
    knowable_time   timestamptz NOT NULL,       -- when it became public. THE time column. See above.
    ingested_at     timestamptz NOT NULL DEFAULT now(),

    title           text NOT NULL,
    body            text,
    language        text,                       -- ISO 639-1 where the source states it

    entities        jsonb NOT NULL DEFAULT '[]',  -- [{kind,value,confidence}] people/companies/tickers/currencies
    geo             text[] NOT NULL DEFAULT '{}', -- ISO 3166-1 alpha-2, plus region codes like 'EU','GCC'
    category        text,                         -- monetary_policy | conflict | election | regulation |
                                                  -- supply_chain | earnings | disaster | protocol_upgrade | ...

    novelty_score   real,                       -- 0..1: how much NEW information vs the last 48h
    amplification   real,                       -- 0..1: cross-source repetition + velocity
    raw_payload     jsonb NOT NULL DEFAULT '{}',-- kept always, so the engine can be rerun over history

    cluster_id      bigint,                     -- set by clustering; FK added after event_clusters exists
    UNIQUE (source, external_id)
);

CREATE INDEX events_knowable_idx    ON events (knowable_time DESC);
CREATE INDEX events_category_idx    ON events (category, knowable_time DESC);
CREATE INDEX events_cluster_idx     ON events (cluster_id);
CREATE INDEX events_geo_idx         ON events USING gin (geo);
CREATE INDEX events_entities_idx    ON events USING gin (entities jsonb_path_ops);

-- Trigram index on the title: this is what makes near-duplicate detection cheap. Embeddings would
-- cluster better, but they need an inference provider, and a spine that stops ingesting whenever
-- model quota runs out is a worse spine. Deterministic first; an embedding pass can refine later.
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX events_title_trgm_idx ON events USING gin (title gin_trgm_ops);


-- One real-world happening, with every source that reported it attached. This is what turns
-- twenty versions of the same story into one Radar card.
CREATE TABLE event_clusters (
    id              bigserial PRIMARY KEY,
    canonical_event bigint REFERENCES events(id) ON DELETE SET NULL,
    title           text NOT NULL,              -- the canonical event's title at formation time
    category        text,
    geo             text[] NOT NULL DEFAULT '{}',
    first_seen      timestamptz NOT NULL,       -- knowable_time of the earliest member
    last_seen       timestamptz NOT NULL,       -- knowable_time of the latest member
    source_count    int NOT NULL DEFAULT 1,     -- DISTINCT sources; corroboration, not volume
    event_count     int NOT NULL DEFAULT 1,
    novelty_score   real,
    amplification   real,
    -- [{at, events, sources}] sampled over time, so the UI can show accelerating vs fading rather
    -- than a single number that hides which way it is moving.
    velocity_curve  jsonb NOT NULL DEFAULT '[]',
    updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX event_clusters_last_seen_idx ON event_clusters (last_seen DESC);
CREATE INDEX event_clusters_category_idx  ON event_clusters (category, last_seen DESC);
CREATE INDEX event_clusters_geo_idx       ON event_clusters USING gin (geo);

ALTER TABLE events ADD CONSTRAINT events_cluster_fk
    FOREIGN KEY (cluster_id) REFERENCES event_clusters(id) ON DELETE SET NULL;


-- Accounts whose statements carry weight because of who is saying them. Seeded manually and
-- editable by the owner (the brief asks for this as first-class data with a management interface,
-- explicitly not a hardcoded array), grouped by domain and country.
CREATE TABLE watchlist_accounts (
    id           bigserial PRIMARY KEY,
    platform     text NOT NULL,                 -- 'bluesky' | 'rss' | 'official' | 'x'
    handle       text NOT NULL,
    display_name text NOT NULL,
    role         text,                          -- 'head_of_state' | 'central_banker' | 'regulator' | ...
    domain       text,                          -- 'monetary_policy' | 'energy' | 'crypto' | ...
    country      text,                          -- ISO 3166-1 alpha-2
    influence    real NOT NULL DEFAULT 0.5,     -- 0..1, the weight their statements carry
    feed_url     text,                          -- where their statements are actually readable
    active       boolean NOT NULL DEFAULT true,
    note         text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (platform, handle)
);

CREATE INDEX watchlist_accounts_active_idx ON watchlist_accounts (active, domain);


-- Every external call with what it cost. Free tiers are tight and the brief requires quota
-- discipline; without this, "why did we get rate limited" is unanswerable and an operator only
-- finds out by watching a panel go empty.
CREATE TABLE source_calls (
    id          bigserial PRIMARY KEY,
    source      text NOT NULL,
    at          timestamptz NOT NULL DEFAULT now(),
    endpoint    text,                           -- path only; NEVER the query string (credentials)
    status      int,
    duration_ms int,
    units       int NOT NULL DEFAULT 1,         -- quota cost, where a source counts in something else
    ok          boolean NOT NULL DEFAULT true
);

CREATE INDEX source_calls_source_at_idx ON source_calls (source, at DESC);

INSERT INTO schema_migrations (version) VALUES (24);
