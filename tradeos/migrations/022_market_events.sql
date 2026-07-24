-- TradeOS migration 022: forward market calendar (Milestone 4, Event & Macro Intelligence).
-- The "what's coming" plane: upcoming EARNINGS (company events) and US MACRO releases (FOMC, CPI, jobs,
-- GDP, PCE, ...). Company events carry a symbol so they connect to the signal + attention planes; macro
-- events carry importance + a country. Idempotent on (source, external_id): a date or a forecast that
-- gets revised updates in place rather than duplicating.

CREATE TABLE market_events (
    id          bigserial PRIMARY KEY,
    kind        text NOT NULL,                 -- 'earnings' | 'fomc' | 'cpi' | 'jobs' | 'gdp' | 'pce' | 'macro'
    scope       text NOT NULL,                 -- 'company' | 'macro'
    title       text NOT NULL,
    event_date  date NOT NULL,
    event_time  text,                          -- 'pre-market' | 'after-hours' | clock time | NULL
    importance  text NOT NULL DEFAULT 'medium',-- 'high' | 'medium' | 'low'
    symbol      text,                          -- company events (nullable for macro)
    entity_id   bigint,
    country     text,                          -- macro events
    source      text NOT NULL,                 -- 'nasdaq/earnings' | 'nasdaq/economic'
    external_id text NOT NULL,
    meta        jsonb NOT NULL DEFAULT '{}',   -- eps_forecast, consensus, previous, market_cap, ...
    created_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source, external_id)
);
CREATE INDEX market_events_date_idx   ON market_events (event_date, importance);
CREATE INDEX market_events_symbol_idx ON market_events (symbol);

INSERT INTO schema_migrations (version) VALUES (22);
