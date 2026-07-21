-- TradeOS migration 015: public-discussion attention & sentiment observations (Slice H).
-- Every row carries its SOURCE and TIMESTAMP; a symbol becomes a "trend" only above a mention floor
-- (in code), attention is a velocity vs the symbol's own baseline, and manipulation is flagged, not
-- hidden. Sentiment scoring never touches the hash-locked convergence signal. Sources with no clean
-- free access (X) or no configured key (Reddit/YouTube) are "not connected", never fabricated.

CREATE TABLE sentiment_observations (
    id            bigserial PRIMARY KEY,
    source        text NOT NULL,             -- 'hn' | 'wikipedia' | 'reddit' | 'youtube'
    symbol        text NOT NULL,
    entity_id     bigint REFERENCES entities(id),
    window_end    timestamptz NOT NULL,      -- end of the counted window (also the knowable time)
    window_hours  integer NOT NULL,
    mentions      integer NOT NULL,
    baseline      real,                       -- typical mentions/window over the trailing period; NULL = no history
    sentiment     real,                       -- -1..1 blended, or NULL when the source has no sentiment
    bots_filtered integer NOT NULL DEFAULT 0, -- accounts removed as bot-like before counting (social sources)
    knowable_time timestamptz NOT NULL,       -- = window_end; point-in-time discipline
    meta          jsonb NOT NULL DEFAULT '{}',
    created_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source, symbol, window_end)
);
CREATE INDEX idx_sentiment_recent ON sentiment_observations (window_end DESC);
CREATE INDEX idx_sentiment_symbol ON sentiment_observations (symbol, window_end DESC);

INSERT INTO schema_migrations (version) VALUES (15);
