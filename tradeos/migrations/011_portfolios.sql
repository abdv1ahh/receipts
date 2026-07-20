-- TradeOS migration 011: paper portfolios — "shadow" the smart money (game-changer Slice C).
-- Positions are paper only. P&L is computed live from real prices_eod vs SPY over the actual
-- holding window; a name we cannot price is reported as 'pending', never filled with a guess.
-- This is the honest, live-building public track record the high-conviction bucket lacks.

CREATE TABLE portfolios (
    id         bigserial PRIMARY KEY,
    user_id    bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name       text NOT NULL,
    kind       text NOT NULL DEFAULT 'manual' CHECK (kind IN ('manual','shadow_bucket')),
    spec       jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_portfolios_user ON portfolios (user_id);

CREATE TABLE portfolio_positions (
    id           bigserial PRIMARY KEY,
    portfolio_id bigint NOT NULL REFERENCES portfolios(id) ON DELETE CASCADE,
    symbol       text NOT NULL,
    entity_id    bigint,
    opened_on    date NOT NULL,             -- paper entry date (a real, knowable trading date)
    note         text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (portfolio_id, symbol)
);
CREATE INDEX idx_portfolio_positions ON portfolio_positions (portfolio_id);

INSERT INTO schema_migrations (version) VALUES (11);
