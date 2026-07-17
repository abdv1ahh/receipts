-- TradeOS migration 008: watchlists (Feature Spec 5.5, build-plan 7.3).
-- Additive. A watchlist is a set of names to watch, never a portfolio to grade. Keyed by
-- user_key ('demo' until Slice 6 auth issues real user ids); no position data is ever stored.

CREATE TABLE watchlists (
    id         bigserial PRIMARY KEY,
    user_key   text NOT NULL DEFAULT 'demo',
    symbol     text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (user_key, symbol)
);
CREATE INDEX idx_watchlists_user ON watchlists (user_key);

INSERT INTO schema_migrations (version) VALUES (8);
