-- TradeOS migration 006: FINRA consolidated short interest (Slice 5), context source.
-- Additive. Two timestamps preserved: settlement_date (event) and knowable_time (publication,
-- ~8 business days later). Only derived quantities are stored/displayed, never a raw-file mirror.

CREATE TABLE short_interest (
    id              bigserial PRIMARY KEY,
    symbol          text NOT NULL,
    issuer_entity   bigint REFERENCES entities(id),
    settlement_date date NOT NULL,          -- event_time
    knowable_time   timestamptz NOT NULL,   -- publication (settlement + ~8 business days, approx)
    current_short   numeric,
    previous_short  numeric,
    change_short    numeric,                 -- current - previous (derived)
    avg_daily_volume numeric,
    days_to_cover   numeric,
    source          text NOT NULL,           -- 'finra:consolidated'
    UNIQUE (symbol, settlement_date)
);
CREATE INDEX idx_short_issuer_knowable ON short_interest (issuer_entity, knowable_time);

INSERT INTO schema_migrations (version) VALUES (6);
