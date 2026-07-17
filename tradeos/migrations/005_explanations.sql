-- TradeOS migration 005: cached plain-language explanations (Slice 5).
-- Additive. Explanations are cached per (cluster, provider); the cluster already pins the
-- definition version, stored here too so a version bump provably invalidates stale prose.
-- A model outage or key exhaustion never blanks the product: the deterministic template is
-- always available and cached model prose still serves.

CREATE TABLE explanation_cache (
    cluster_id         bigint NOT NULL REFERENCES signal_clusters(id),
    provider           text   NOT NULL,          -- 'template' | 'gemini' | 'anthropic'
    definition_version integer NOT NULL,
    prose              text   NOT NULL,
    model_id           text   NOT NULL,          -- e.g. 'template' | 'gemini-2.x' — shown to the user
    used_template      boolean NOT NULL DEFAULT false,  -- true when a guard forced the fallback
    created_at         timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (cluster_id, provider)
);

INSERT INTO schema_migrations (version) VALUES (5);
