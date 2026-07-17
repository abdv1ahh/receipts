-- TradeOS migration 007: intelligence library (Slice 5, build-plan 7.1).
-- Additive. The education layer that teaches in the same moment the product informs, and the
-- strongest anchor on the education side of the regulatory line. Content is original prose;
-- every factual claim traces to a listed public source (no copyrighted reproduction).

CREATE TABLE library_entries (
    id                    bigserial PRIMARY KEY,
    slug                  text UNIQUE NOT NULL,
    kind                  text NOT NULL CHECK (kind IN ('concept','investor_profile')),
    title                 text NOT NULL,
    body_md               text NOT NULL,
    sources               jsonb NOT NULL,          -- [{title, url, basis: public_domain|public_filing|published_interview}]
    linked_source_classes text[] NOT NULL DEFAULT '{}',   -- match a cluster's classes -> "Understand this pattern"
    review_status         text NOT NULL DEFAULT 'draft',  -- founder review gate before publish
    created_at            timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_library_classes ON library_entries USING gin (linked_source_classes);

INSERT INTO schema_migrations (version) VALUES (7);
