-- Migration 025: claims, outcomes, and the exposure reference data (Phase 3).
--
-- This is the heart of the product. An event says what happened; a CLAIM says what it means and
-- commits to it — mechanism, what it touches, over what horizon, with what confidence — and is
-- timestamped the moment it is made so it can be scored later against what actually happened.
--
-- The Ledger is not a separate store. It is what you get by reading claims joined to outcomes,
-- which is the point: there is no second copy of the record that could flatter the first.
--
-- Point-in-time discipline carries through. `created_at` is when the claim was made and nothing
-- may be backdated into it; outcome measurement only ever reads prices strictly after that.

CREATE TABLE claims (
    id              bigserial PRIMARY KEY,
    event_id        bigint REFERENCES events(id) ON DELETE CASCADE,
    cluster_id      bigint REFERENCES event_clusters(id) ON DELETE SET NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),   -- when the interpretation was made
    model_version   text NOT NULL,                        -- provider:model, or 'template'

    -- Prose: HOW this propagates, causally. "This is bullish for oil" is not a mechanism.
    -- "This route carries a fifth of seaborne crude, and closure forces rerouting that adds days
    -- of voyage time, tightening supply on a delivery basis before a production basis" is.
    mechanism       text NOT NULL,

    -- [{kind: asset|sector|currency|region, value, direction: up|down, magnitude: small|moderate|large}]
    affected        jsonb NOT NULL DEFAULT '[]',

    horizon         text NOT NULL,                        -- hours | days | weeks | months
    horizon_days    int NOT NULL,                         -- the same thing, resolvable for scoring

    -- 0..1, never hidden. A prediction without its confidence attached is how users get hurt.
    confidence      real NOT NULL CHECK (confidence >= 0 AND confidence <= 1),

    analogs         jsonb NOT NULL DEFAULT '[]',          -- [{when, what, what_followed}]
    contradicts     bigint[] NOT NULL DEFAULT '{}',       -- live claims pulling the other way
    reasoning_trace jsonb NOT NULL DEFAULT '[]',          -- the chain, exposed on demand

    -- Set when the claim's horizon elapses and it gets scored. Kept on the claim so a Ledger
    -- query is one join, and so a claim can never be silently unscored.
    resolved_at     timestamptz,
    status          text NOT NULL DEFAULT 'open'          -- open | resolved | unscoreable
                    CHECK (status IN ('open', 'resolved', 'unscoreable'))
);

CREATE INDEX claims_created_idx   ON claims (created_at DESC);
CREATE INDEX claims_event_idx     ON claims (event_id);
CREATE INDEX claims_cluster_idx   ON claims (cluster_id);
CREATE INDEX claims_status_idx    ON claims (status, created_at DESC);
CREATE INDEX claims_affected_idx  ON claims USING gin (affected jsonb_path_ops);


-- What actually happened. One row per (claim, affected asset) — a claim naming three assets is
-- scored three times, because getting one right and two wrong is not "right".
CREATE TABLE claim_outcomes (
    id            bigserial PRIMARY KEY,
    claim_id      bigint NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
    subject       text NOT NULL,                    -- the asset/sector/currency this row scores
    predicted     text NOT NULL,                    -- 'up' | 'down'
    magnitude     text,                             -- the band the claim committed to
    measured_at   timestamptz NOT NULL DEFAULT now(),
    entry_day     date,                             -- first trading day strictly after the claim
    exit_day      date,
    actual_return real,                             -- the asset's own return over the horizon
    excess_return real,                             -- vs SPY, so a whole-market move is not credit
    verdict       text NOT NULL                     -- hit | miss | inconclusive | unscoreable
                  CHECK (verdict IN ('hit', 'miss', 'inconclusive', 'unscoreable')),
    note          text,                             -- WHY, when it is not a clean hit or miss
    UNIQUE (claim_id, subject)
);

CREATE INDEX claim_outcomes_verdict_idx ON claim_outcomes (verdict);


-- Country-level exposure: what makes the same event read differently from Sharjah than São Paulo.
-- Deliberately small and hand-curated rather than exhaustive — the brief's own guidance. Every
-- row is a stated fact with a source, not a computed estimate.
CREATE TABLE country_exposure (
    country          text PRIMARY KEY,              -- ISO 3166-1 alpha-2
    name             text NOT NULL,
    currency         text NOT NULL,                 -- ISO 4217
    currency_regime  text,                          -- floating | managed | pegged_usd | pegged_eur
    pegged_to        text,
    main_index       text,                          -- the index a local reader actually watches
    export_partners  text[] NOT NULL DEFAULT '{}',  -- ISO codes, largest first
    import_partners  text[] NOT NULL DEFAULT '{}',
    key_exports      text[] NOT NULL DEFAULT '{}',  -- commodity/sector names
    key_imports      text[] NOT NULL DEFAULT '{}',
    commodity_exposure jsonb NOT NULL DEFAULT '{}', -- {oil: "exporter", wheat: "importer", ...}
    source           text,                          -- where these figures came from
    updated_at       timestamptz NOT NULL DEFAULT now()
);


-- The personal frame. Relevance scoring is meaningless without it, so onboarding (Phase 8) exists
-- mainly to fill this in.
CREATE TABLE user_profiles (
    user_id       bigint PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    country       text REFERENCES country_exposure(country),
    base_currency text,
    sectors       text[] NOT NULL DEFAULT '{}',
    risk_appetite text,                             -- conservative | balanced | aggressive
    updated_at    timestamptz NOT NULL DEFAULT now()
);

INSERT INTO schema_migrations (version) VALUES (25);
