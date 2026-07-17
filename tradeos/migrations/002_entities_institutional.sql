-- TradeOS migration 002: entity resolution + institutional pipelines (Slice 2).
-- Additive only. One asset becomes recognizable across a Form 4, a 13D, and a 13F;
-- one institution across every document it files. Point-in-time discipline preserved:
-- every derived fact still carries event_time and knowable_time.

-- ---------------------------------------------------------------- canonical entities
CREATE TABLE entities (
    id          bigserial PRIMARY KEY,
    kind        text NOT NULL CHECK (kind IN ('issuer','institution','insider')),
    cik         text UNIQUE,               -- primary resolver for all EDGAR-known entities
    name        text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- issuer <-> ticker/identifier mapping, with confidence and provenance
CREATE TABLE security_map (
    id          bigserial PRIMARY KEY,
    entity_id   bigint NOT NULL REFERENCES entities(id),
    symbol      text,
    cusip       text,                       -- stored when a filing/OpenFIGI provides it; never purchased
    figi        text,                       -- from OpenFIGI when resolvable
    source      text NOT NULL,              -- 'sec_company_tickers' | 'filing' | 'openfigi'
    confidence  real NOT NULL,              -- 1.0 exact CIK map, lower for identifier joins
    valid_from  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (entity_id, symbol, cusip)
);
-- cusip-null rows (from company_tickers) need their own idempotency key: NULLs are
-- distinct under a plain UNIQUE, so re-running sync-tickers would duplicate without this.
CREATE UNIQUE INDEX uq_security_map_symbol_nocusip
    ON security_map (entity_id, symbol) WHERE cusip IS NULL;
CREATE INDEX idx_security_map_cusip ON security_map (cusip) WHERE cusip IS NOT NULL;
CREATE INDEX idx_security_map_symbol ON security_map (symbol) WHERE symbol IS NOT NULL;

-- ------------------------------------------------------------- 13D/13G stake events
CREATE TABLE stake_events (
    id               bigserial PRIMARY KEY,
    accession_no     text NOT NULL REFERENCES raw_filings(accession_no),
    form_type        text NOT NULL,         -- 'SCHEDULE 13D','SCHEDULE 13G','SCHEDULE 13D/A','SCHEDULE 13G/A'
    amends_accession text,                  -- usually NULL: EDGAR headers do not carry the parent accession
    file_number      text,                  -- SEC FILE NUMBER (005-xxxxx): the amendment-series key
    filer_entity     bigint NOT NULL REFERENCES entities(id),
    issuer_entity    bigint REFERENCES entities(id),   -- NULL if unresolved; display as unresolved
    issuer_name_raw  text NOT NULL,
    percent_owned    numeric,               -- NULL for the demo: never scraped from ambiguous HTML cover pages
    event_time       date NOT NULL,         -- date of event requiring filing, or filing-date fallback
    knowable_time    timestamptz NOT NULL,  -- acceptance datetime
    parse_confidence text NOT NULL,         -- 'header_period' | 'filing_date_fallback'
    activist         boolean NOT NULL,      -- true for the 13D family
    UNIQUE (accession_no, filer_entity, issuer_name_raw)
);
CREATE INDEX idx_stakes_issuer_knowable ON stake_events (issuer_entity, knowable_time);
CREATE INDEX idx_stakes_file_number ON stake_events (file_number);

-- --------------------------------------------------------------- 13F quarterly holdings
CREATE TABLE fund_holdings (
    id              bigserial PRIMARY KEY,
    accession_no    text NOT NULL REFERENCES raw_filings(accession_no),
    filer_entity    bigint NOT NULL REFERENCES entities(id),
    period_end      date NOT NULL,          -- quarter end: the event_time of the snapshot
    knowable_time   timestamptz NOT NULL,   -- acceptance time, up to 45 days later; the staleness gap
    cusip           text NOT NULL,
    issuer_name_raw text NOT NULL,
    issuer_entity   bigint REFERENCES entities(id),
    value_usd       numeric,                -- normalized to whole USD (decision log #17)
    shares          numeric,                -- summed within the filing per (cusip, share_type) (decision log #18)
    share_type      text,                   -- 'SH' or 'PRN'
    UNIQUE (accession_no, cusip, share_type)
);
CREATE INDEX idx_holdings_issuer_knowable ON fund_holdings (issuer_entity, knowable_time);
CREATE INDEX idx_holdings_filer ON fund_holdings (filer_entity);

-- ------------------------------------------------ link existing insider rows to entities
ALTER TABLE insider_transactions ADD COLUMN issuer_entity bigint REFERENCES entities(id);
CREATE INDEX idx_insider_issuer_entity ON insider_transactions (issuer_entity, knowable_time);

INSERT INTO schema_migrations (version) VALUES (2);
