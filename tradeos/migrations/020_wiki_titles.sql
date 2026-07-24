-- TradeOS migration 020: Wikipedia article-title cache for the attention source (Milestone 2).
-- Resolving a company name to its canonical Wikipedia article (e.g. "NVIDIA CORP" -> "Nvidia") is a
-- search call we don't want to repeat every ingest. One row per tracked symbol; resolved_ok=false
-- records an HONEST miss (no article found) so we never fetch pageviews for a fabricated title.

CREATE TABLE wiki_titles (
    symbol      text PRIMARY KEY,
    entity_id   bigint,
    title       text,                         -- canonical article title, NULL when unresolved
    resolved_ok boolean NOT NULL DEFAULT false,
    resolved_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO schema_migrations (version) VALUES (20);
