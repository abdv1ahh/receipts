-- TradeOS migration 003: versioned signals + computed convergence clusters (Slice 3).
-- Additive only. The definition is product: params and the code_hash that locks the
-- computing logic live in the DB, and every version change is a visible, logged event.

CREATE TABLE signal_definitions (
    id          bigserial PRIMARY KEY,
    name        text NOT NULL,            -- 'convergence'
    version     integer NOT NULL,
    params      jsonb NOT NULL,           -- every constant lives here, not hard-coded in logic
    code_hash   text NOT NULL,            -- sha256 of the computing module file
    changelog   text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (name, version)
);

CREATE TABLE signal_clusters (
    id                bigserial PRIMARY KEY,
    definition_id     bigint NOT NULL REFERENCES signal_definitions(id),
    issuer_entity     bigint NOT NULL REFERENCES entities(id),
    as_of             timestamptz NOT NULL,  -- computation time; all inputs have knowable_time <= as_of
    score             numeric NOT NULL,
    confidence_bucket text NOT NULL CHECK (confidence_bucket IN ('low','medium','high')),
    voices            integer NOT NULL,      -- distinct independent voices contributing
    source_classes    text[] NOT NULL,       -- e.g. {insider,activist}
    inputs            jsonb NOT NULL,        -- exact contributing events: ids, weights, decayed values, floor status
    UNIQUE (definition_id, issuer_entity, as_of)
);
CREATE INDEX idx_clusters_asof ON signal_clusters (as_of DESC);
CREATE INDEX idx_clusters_issuer ON signal_clusters (issuer_entity, as_of DESC);

INSERT INTO schema_migrations (version) VALUES (3);
