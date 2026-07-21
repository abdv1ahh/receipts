-- TradeOS migration 018: journal-report cache (Slice L, advanced AI).
-- The auto journal report aggregates a user's whole journal and (optionally) has the model phrase it.
-- Like trade_analyses (migration 014), we cache the result keyed by an inputs-hash of the journal, so
-- re-opening the report doesn't re-spend the LLM quota; it regenerates only when the journal changes
-- or the provider changes. One row per user. A genuine model success is cached; a template fallback
-- from a model provider is not (the app layer enforces that, mirroring trade_analyses).

CREATE TABLE journal_reports (
    user_id       bigint PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    input_hash    char(64) NOT NULL,
    provider      text NOT NULL,
    model_id      text NOT NULL,
    used_template boolean NOT NULL,
    content       jsonb NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now()
);

INSERT INTO schema_migrations (version) VALUES (18);
