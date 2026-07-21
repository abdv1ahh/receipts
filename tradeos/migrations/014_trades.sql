-- TradeOS migration 014: user trade journal + AI analysis cache (Slice E).
-- Users log their OWN trades. This is journaling and post-hoc education, not advice: every AI
-- analysis is generated through the same directive/number guards as the signal explanation layer,
-- so it can only describe, frame risk, and teach — never tell a user to buy/sell/hold. Trades are
-- PRIVATE by default; publishing is an explicit, revocable choice. Images are re-encoded server-side
-- (EXIF stripped, polyglots neutralized) and stored under an opaque key, never a user filename.

CREATE TABLE trades (
    id               bigserial PRIMARY KEY,
    user_id          bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    symbol           text,                          -- nullable: not every idea is a resolvable ticker
    entity_id        bigint,                        -- resolved issuer, when the symbol maps to one
    asset_class      text NOT NULL DEFAULT 'equity' CHECK (asset_class IN ('equity','crypto','forex','option','future','other')),
    direction        text NOT NULL DEFAULT 'long'   CHECK (direction IN ('long','short')),
    status           text NOT NULL DEFAULT 'planned' CHECK (status IN ('planned','open','closed')),
    entry_price      double precision,
    exit_price       double precision,
    stop_price       double precision,
    target_price     double precision,
    size             double precision,
    size_unit        text NOT NULL DEFAULT 'shares' CHECK (size_unit IN ('shares','contracts','usd','units','lots')),
    timeframe        text,                          -- scalp/day/swing/position/leaps (short, free text)
    strategy         text,                          -- short label, e.g. "breakout", "mean reversion"
    reason_entry     text,
    reason_exit      text,
    confidence       smallint CHECK (confidence BETWEEN 1 AND 5),
    expected_outcome text,
    opened_on        date,
    closed_on        date,
    image_path       text,                          -- opaque key under UPLOADS_DIR, or NULL
    is_public        boolean NOT NULL DEFAULT false,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_trades_user ON trades (user_id, created_at DESC);
CREATE INDEX idx_trades_public ON trades (created_at DESC) WHERE is_public;
CREATE INDEX idx_trades_symbol ON trades (symbol);

-- Cached educational analysis for a trade, keyed by a hash of the analyzed inputs so it
-- regenerates only when the trade's material fields change (mirrors explanation_cache).
CREATE TABLE trade_analyses (
    trade_id      bigint PRIMARY KEY REFERENCES trades(id) ON DELETE CASCADE,
    input_hash    text NOT NULL,
    provider      text NOT NULL,
    model_id      text NOT NULL,
    used_template boolean NOT NULL DEFAULT true,
    content       jsonb NOT NULL,                   -- {reward_risk, observations[], risk_flags[], context[], learn[], prose}
    created_at    timestamptz NOT NULL DEFAULT now()
);

INSERT INTO schema_migrations (version) VALUES (14);
