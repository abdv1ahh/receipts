-- TradeOS migration 004: end-of-day prices + backtest outcomes (Slice 4).
-- Additive only. Prices are source-agnostic (the `source` column records the feed and the
-- adjustment series used); outcomes carry NULL until a horizon has actually closed.

CREATE TABLE prices_eod (
    symbol  text    NOT NULL,
    day     date    NOT NULL,
    open    numeric,
    high    numeric,
    low     numeric,
    close   numeric NOT NULL,
    volume  numeric,
    source  text    NOT NULL,        -- e.g. 'tiingo:adjusted' | 'alphavantage:adjusted'; records the series used
    PRIMARY KEY (symbol, day)
);
CREATE INDEX idx_prices_symbol_day ON prices_eod (symbol, day);

CREATE TABLE signal_outcomes (
    cluster_id  bigint PRIMARY KEY REFERENCES signal_clusters(id),
    entry_day   date NOT NULL,       -- first trading day after the cluster's as_of
    excess_30   numeric,             -- excess return vs SPY; NULL until the horizon closes / prices exist
    excess_90   numeric,
    excess_180  numeric,
    computed_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO schema_migrations (version) VALUES (4);
