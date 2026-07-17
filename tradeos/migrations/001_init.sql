-- TradeOS migration 001: the honesty architecture, in DDL.
-- Raw layer is append-only and immutable (enforced by trigger, not convention).
-- Every derived fact carries event_time and knowable_time.

CREATE TABLE schema_migrations (
    version     integer PRIMARY KEY,
    applied_at  timestamptz NOT NULL DEFAULT now()
);

-- ------------------------------------------------------------------ raw layer
CREATE TABLE raw_filings (
    id           bigserial PRIMARY KEY,
    source       text        NOT NULL,               -- 'edgar/form4', later 'edgar/13d', ...
    accession_no text        NOT NULL UNIQUE,        -- idempotency key: re-ingestion is a no-op
    source_url   text        NOT NULL,
    sha256       char(64)    NOT NULL,
    fetched_at   timestamptz NOT NULL DEFAULT now(),
    accepted_at  timestamptz NOT NULL,               -- knowable_time, from EDGAR header (US/Eastern)
    payload      bytea       NOT NULL                -- full original document; derived tables rebuild from here
);

CREATE FUNCTION forbid_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'raw layer is append-only: % on % is forbidden', TG_OP, TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER raw_filings_immutable
    BEFORE UPDATE OR DELETE ON raw_filings
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

-- --------------------------------------------------------------- derived layer
CREATE TABLE insider_transactions (
    id               bigserial PRIMARY KEY,
    accession_no     text        NOT NULL REFERENCES raw_filings(accession_no),
    seq              integer     NOT NULL,           -- position within the filing
    form_type        text        NOT NULL,           -- '4' or '4/A'; amendments link, never overwrite
    amends_accession text,                           -- for 4/A: the accession it amends, when stated
    issuer_cik       text        NOT NULL,
    issuer_name      text        NOT NULL,
    symbol           text,
    owner_cik        text        NOT NULL,
    owner_name       text        NOT NULL,
    is_director      boolean     NOT NULL DEFAULT false,
    is_officer       boolean     NOT NULL DEFAULT false,
    officer_title    text,
    security_title   text        NOT NULL,
    transaction_code text        NOT NULL,
    event_time       date        NOT NULL,           -- when the insider traded
    knowable_time    timestamptz NOT NULL,           -- when the filing became public
    shares           numeric,
    price_per_share  numeric,
    acquired_disposed char(1)    NOT NULL,
    shares_after     numeric,
    direct_indirect  char(1),
    UNIQUE (accession_no, seq, owner_cik)
);

CREATE INDEX idx_insider_symbol_knowable ON insider_transactions (symbol, knowable_time);
CREATE INDEX idx_insider_issuer_knowable ON insider_transactions (issuer_cik, knowable_time);

-- ------------------------------------------------------- loud-degradation layer
CREATE TABLE ingest_rejects (
    id           bigserial PRIMARY KEY,
    source       text        NOT NULL,
    accession_no text,
    reason       text        NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE feed_health (
    source               text PRIMARY KEY,
    last_success_at      timestamptz,
    last_record_knowable timestamptz,
    records_total        bigint NOT NULL DEFAULT 0,
    rejects_total        bigint NOT NULL DEFAULT 0,
    note                 text
);

INSERT INTO schema_migrations (version) VALUES (1);
