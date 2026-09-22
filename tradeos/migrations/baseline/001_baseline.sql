-- 001_baseline.sql — the whole schema a fresh Receipts install needs, in one file.
--
-- WHAT THIS IS. `tradeos/migrations/*.sql` is 37 ordered files describing the research platform
-- this product was extracted from: an event spine, a claim engine, a convergence signal, a trade
-- journal, portfolios, a community, billing. Replaying them on a new install would create 64
-- tables so that 19 of them could be used. This is `pg_dump --schema-only` of those 19, plus the
-- three trigger FUNCTIONS pg_dump's per-table mode does not emit, plus the extensions, plus a
-- schema_migrations row for every one of the 37 it stands in for.
--
-- WHICH DATABASE GETS WHICH. `db.run_migrations` chooses: an EMPTY database (no
-- schema_migrations) gets this file; a database with history gets the 37, exactly as before. The
-- author's own database has all 37 applied and is untouched by this change — it never reads this
-- file, and the rows below would be no-ops there anyway.
--
-- THE TRIGGERS ARE THE PRODUCT AND THEY ARE THE REASON THIS FILE IS HAND-ASSEMBLED.
-- `pg_dump -t table` emits CREATE TRIGGER and NOT the function the trigger calls, because the
-- function is not part of any table. A baseline built by piping pg_dump into a file therefore
-- installs `calls_append_only_trg` pointing at a function that does not exist — and Postgres
-- accepts that at CREATE time and fails at the first UPDATE. Measured here: the raw dump of 21
-- tables contained 3 CREATE TRIGGER statements and 0 CREATE FUNCTION. An append-only record whose
-- append-only trigger is broken is the single worst thing this schema could ship, so the three
-- functions are emitted explicitly below, before the tables that reference them.
--
--   forbid_mutation            audit_log cannot be edited or deleted
--   callers_handle_immutable   a handle cannot change hands or spelling once claimed
--   calls_append_only          a call cannot be deleted; before resolution only the resolution
--                              columns may be filled in; after resolution NOTHING may change,
--                              including the nine figures the verdict was computed from
--
-- VERIFIED BY CONSTRUCTION, not by reading: `tests/test_migrations.py` migrates one empty
-- database from this file and another from the 37, and diffs `pg_dump --schema-only` of both.
-- They must be identical.
--
-- Written 2026-09-23. Every migration must insert its own schema_migrations row (CLAUDE.md §9);
-- this one inserts 1..37 at the end, so an install started here can never re-run any of them.

CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS pg_trgm;


-- ------------------------------------------------------------------ trigger functions
--
-- Emitted before the tables, because CREATE TRIGGER resolves its function at creation time.

CREATE OR REPLACE FUNCTION public.forbid_mutation()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
BEGIN
    RAISE EXCEPTION 'raw layer is append-only: % on % is forbidden', TG_OP, TG_TABLE_NAME;
END;
$function$
;

CREATE OR REPLACE FUNCTION public.callers_handle_immutable()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
BEGIN
    IF OLD.handle IS DISTINCT FROM NEW.handle
       AND EXISTS (SELECT 1 FROM calls WHERE caller_id = OLD.id) THEN
        RAISE EXCEPTION 'a handle cannot change once a call has been published under it';
    END IF;
    RETURN NEW;
END;
$function$
;

CREATE OR REPLACE FUNCTION public.calls_append_only()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'calls rows are append only and cannot be deleted';
    END IF;

    -- The commitment: exactly the fields the hash covers, plus the frozen context.
    IF OLD.caller_id        IS DISTINCT FROM NEW.caller_id
    OR OLD.seq              IS DISTINCT FROM NEW.seq
    OR OLD.symbol           IS DISTINCT FROM NEW.symbol
    OR OLD.direction        IS DISTINCT FROM NEW.direction
    OR OLD.horizon_days     IS DISTINCT FROM NEW.horizon_days
    OR OLD.confidence       IS DISTINCT FROM NEW.confidence
    OR OLD.thesis           IS DISTINCT FROM NEW.thesis
    OR OLD.published_at     IS DISTINCT FROM NEW.published_at
    OR OLD.knowable_time    IS DISTINCT FROM NEW.knowable_time
    OR OLD.prev_hash        IS DISTINCT FROM NEW.prev_hash
    OR OLD.content_hash     IS DISTINCT FROM NEW.content_hash
    OR OLD.benchmark_symbol IS DISTINCT FROM NEW.benchmark_symbol
    OR OLD.context_snapshot IS DISTINCT FROM NEW.context_snapshot THEN
        RAISE EXCEPTION 'sealed columns on calls are immutable';
    END IF;

    -- The measurement. Once scored, every figure the verdict rests on is frozen with it -- and
    -- now the open-reason columns too, which must read NULL on a resolved call rather than
    -- carrying a stale excuse somebody could add afterwards.
    IF OLD.resolved_at IS NOT NULL THEN
        IF OLD.verdict          IS DISTINCT FROM NEW.verdict
        OR OLD.verdict_note     IS DISTINCT FROM NEW.verdict_note
        OR OLD.resolved_at      IS DISTINCT FROM NEW.resolved_at
        OR OLD.entry_session    IS DISTINCT FROM NEW.entry_session
        OR OLD.exit_session     IS DISTINCT FROM NEW.exit_session
        OR OLD.entry_price      IS DISTINCT FROM NEW.entry_price
        OR OLD.exit_price       IS DISTINCT FROM NEW.exit_price
        OR OLD.benchmark_entry  IS DISTINCT FROM NEW.benchmark_entry
        OR OLD.benchmark_exit   IS DISTINCT FROM NEW.benchmark_exit
        OR OLD.subject_return   IS DISTINCT FROM NEW.subject_return
        OR OLD.benchmark_return IS DISTINCT FROM NEW.benchmark_return
        OR OLD.excess_return    IS DISTINCT FROM NEW.excess_return
        OR OLD.open_reason_code IS DISTINCT FROM NEW.open_reason_code
        OR OLD.open_reason      IS DISTINCT FROM NEW.open_reason
        OR OLD.open_checked_at  IS DISTINCT FROM NEW.open_checked_at THEN
            RAISE EXCEPTION 'a resolved call is immutable, including the figures it was scored on';
        END IF;
    END IF;

    -- A verdict without a resolved_at would sidestep the block above entirely.
    IF NEW.verdict IS NOT NULL AND NEW.resolved_at IS NULL THEN
        RAISE EXCEPTION 'a verdict must be written together with its resolved_at';
    END IF;

    RETURN NEW;
END;
$function$
;


-- ------------------------------------------------------------------ tables, indexes, constraints, triggers

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: api_keys; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.api_keys (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    name text,
    prefix text NOT NULL,
    key_hash character(64) NOT NULL,
    scopes text[] DEFAULT '{read}'::text[] NOT NULL,
    canary text NOT NULL,
    last_used_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    revoked_at timestamp with time zone
);

--
-- Name: api_keys_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.api_keys_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

--
-- Name: api_keys_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.api_keys_id_seq OWNED BY public.api_keys.id;

--
-- Name: audit_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.audit_log (
    id bigint NOT NULL,
    actor text,
    action text NOT NULL,
    object text,
    at timestamp with time zone DEFAULT now() NOT NULL,
    detail jsonb
);

--
-- Name: audit_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.audit_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

--
-- Name: audit_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.audit_log_id_seq OWNED BY public.audit_log.id;

--
-- Name: auth_tokens; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.auth_tokens (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    purpose text NOT NULL,
    token_hash character(64) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    used_at timestamp with time zone,
    CONSTRAINT auth_tokens_purpose_check CHECK ((purpose = ANY (ARRAY['verify_email'::text, 'reset_password'::text])))
);

--
-- Name: auth_tokens_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.auth_tokens_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

--
-- Name: auth_tokens_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.auth_tokens_id_seq OWNED BY public.auth_tokens.id;

--
-- Name: caller_verifications; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.caller_verifications (
    id bigint NOT NULL,
    caller_id bigint NOT NULL,
    code text NOT NULL,
    method text NOT NULL,
    evidence_url text,
    status text DEFAULT 'pending'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    resolved_at timestamp with time zone,
    CONSTRAINT caller_verifications_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'confirmed'::text, 'rejected'::text])))
);

--
-- Name: caller_verifications_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.caller_verifications_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

--
-- Name: caller_verifications_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.caller_verifications_id_seq OWNED BY public.caller_verifications.id;

--
-- Name: callers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.callers (
    id bigint NOT NULL,
    user_id bigint,
    handle text NOT NULL,
    display_name text NOT NULL,
    bio text,
    kind text DEFAULT 'human'::text NOT NULL,
    is_house boolean DEFAULT false NOT NULL,
    audience_url text,
    verified_at timestamp with time zone,
    verification_method text,
    verification_evidence_url text,
    jurisdiction_attested boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT callers_kind_check CHECK ((kind = ANY (ARRAY['human'::text, 'algorithm'::text]))),
    CONSTRAINT callers_verification_method_check CHECK ((verification_method = ANY (ARRAY['public_post'::text, 'meta_tag'::text, 'wallet_signature'::text, 'house'::text])))
);

--
-- Name: callers_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.callers_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

--
-- Name: callers_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.callers_id_seq OWNED BY public.callers.id;

--
-- Name: calls; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.calls (
    id bigint NOT NULL,
    caller_id bigint NOT NULL,
    seq integer NOT NULL,
    symbol text NOT NULL,
    direction text NOT NULL,
    horizon_days integer NOT NULL,
    confidence text NOT NULL,
    thesis text NOT NULL,
    benchmark_symbol text DEFAULT 'SPY'::text NOT NULL,
    published_at timestamp with time zone NOT NULL,
    knowable_time timestamp with time zone NOT NULL,
    prev_hash text NOT NULL,
    content_hash text NOT NULL,
    entry_session date,
    exit_session date,
    entry_price numeric,
    exit_price numeric,
    benchmark_entry numeric,
    benchmark_exit numeric,
    subject_return numeric,
    benchmark_return numeric,
    excess_return numeric,
    verdict text,
    verdict_note text,
    resolved_at timestamp with time zone,
    context_snapshot jsonb,
    open_reason_code text,
    open_reason text,
    open_checked_at timestamp with time zone,
    CONSTRAINT calls_confidence_check CHECK ((confidence = ANY (ARRAY['low'::text, 'medium'::text, 'high'::text]))),
    CONSTRAINT calls_direction_check CHECK ((direction = ANY (ARRAY['up'::text, 'down'::text]))),
    CONSTRAINT calls_horizon_days_check CHECK ((horizon_days = ANY (ARRAY[7, 30, 90]))),
    CONSTRAINT calls_open_reason_code_check CHECK (((open_reason_code IS NULL) OR (open_reason_code = ANY (ARRAY['waiting_for_benchmark'::text, 'waiting_for_subject_price'::text, 'subject_series_ended'::text])))),
    CONSTRAINT calls_verdict_check CHECK ((verdict = ANY (ARRAY['hit'::text, 'miss'::text, 'inconclusive'::text, 'unscoreable'::text])))
);

--
-- Name: calls_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.calls_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

--
-- Name: calls_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.calls_id_seq OWNED BY public.calls.id;

--
-- Name: feature_flags; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.feature_flags (
    name text NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    blocked_countries text[] DEFAULT '{}'::text[] NOT NULL
);

--
-- Name: feed_health; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.feed_health (
    source text NOT NULL,
    last_success_at timestamp with time zone,
    last_record_knowable timestamp with time zone,
    records_total bigint DEFAULT 0 NOT NULL,
    rejects_total bigint DEFAULT 0 NOT NULL,
    note text
);

--
-- Name: ingest_rejects; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ingest_rejects (
    id bigint NOT NULL,
    source text NOT NULL,
    accession_no text,
    reason text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

--
-- Name: ingest_rejects_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ingest_rejects_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

--
-- Name: ingest_rejects_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ingest_rejects_id_seq OWNED BY public.ingest_rejects.id;

--
-- Name: invites; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.invites (
    code text NOT NULL,
    created_by bigint,
    used_by bigint,
    used_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

--
-- Name: job_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.job_runs (
    id bigint NOT NULL,
    job text NOT NULL,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    finished_at timestamp with time zone,
    status text,
    detail jsonb,
    duration_ms integer,
    CONSTRAINT job_runs_status_known CHECK (((status IS NULL) OR (status = ANY (ARRAY['ok'::text, 'warning'::text, 'error'::text]))))
);

--
-- Name: job_runs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.job_runs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

--
-- Name: job_runs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.job_runs_id_seq OWNED BY public.job_runs.id;

--
-- Name: login_attempts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.login_attempts (
    id bigint NOT NULL,
    key text NOT NULL,
    at timestamp with time zone DEFAULT now() NOT NULL
);

--
-- Name: login_attempts_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.login_attempts_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

--
-- Name: login_attempts_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.login_attempts_id_seq OWNED BY public.login_attempts.id;

--
-- Name: oauth_identities; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.oauth_identities (
    id bigint NOT NULL,
    provider text NOT NULL,
    subject text NOT NULL,
    user_id bigint NOT NULL,
    email text,
    linked_at timestamp with time zone DEFAULT now() NOT NULL,
    last_login timestamp with time zone
);

--
-- Name: oauth_identities_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.oauth_identities_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

--
-- Name: oauth_identities_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.oauth_identities_id_seq OWNED BY public.oauth_identities.id;

--
-- Name: oauth_states; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.oauth_states (
    state text NOT NULL,
    provider text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    redirect_to text
);

--
-- Name: prices_eod; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.prices_eod (
    symbol text NOT NULL,
    day date NOT NULL,
    open numeric,
    high numeric,
    low numeric,
    close numeric NOT NULL,
    volume numeric,
    source text NOT NULL
);

--
-- Name: schema_migrations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.schema_migrations (
    version integer NOT NULL,
    applied_at timestamp with time zone DEFAULT now() NOT NULL
);

--
-- Name: sessions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sessions (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    token_hash character(64) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    ip text,
    ua text
);

--
-- Name: sessions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.sessions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

--
-- Name: sessions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.sessions_id_seq OWNED BY public.sessions.id;

--
-- Name: subscriptions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.subscriptions (
    user_id bigint NOT NULL,
    plan text DEFAULT 'free'::text NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    provider text,
    provider_customer_id text,
    provider_subscription_id text,
    current_period_end timestamp with time zone,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT subscriptions_plan_check CHECK ((plan = ANY (ARRAY['free'::text, 'retail'::text, 'pro'::text]))),
    CONSTRAINT subscriptions_status_check CHECK ((status = ANY (ARRAY['active'::text, 'past_due'::text, 'canceled'::text, 'trialing'::text])))
);

--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users (
    id bigint NOT NULL,
    email public.citext NOT NULL,
    password_hash text NOT NULL,
    tier text DEFAULT 'free'::text NOT NULL,
    totp_secret text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    referral_code text,
    referred_by bigint,
    handle public.citext,
    bio text,
    banned boolean DEFAULT false NOT NULL,
    email_verified_at timestamp with time zone,
    CONSTRAINT users_tier_check CHECK ((tier = ANY (ARRAY['free'::text, 'retail'::text, 'pro'::text, 'admin'::text])))
);

--
-- Name: users_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.users_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

--
-- Name: users_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.users_id_seq OWNED BY public.users.id;

--
-- Name: api_keys id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_keys ALTER COLUMN id SET DEFAULT nextval('public.api_keys_id_seq'::regclass);

--
-- Name: audit_log id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_log ALTER COLUMN id SET DEFAULT nextval('public.audit_log_id_seq'::regclass);

--
-- Name: auth_tokens id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_tokens ALTER COLUMN id SET DEFAULT nextval('public.auth_tokens_id_seq'::regclass);

--
-- Name: caller_verifications id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.caller_verifications ALTER COLUMN id SET DEFAULT nextval('public.caller_verifications_id_seq'::regclass);

--
-- Name: callers id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.callers ALTER COLUMN id SET DEFAULT nextval('public.callers_id_seq'::regclass);

--
-- Name: calls id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.calls ALTER COLUMN id SET DEFAULT nextval('public.calls_id_seq'::regclass);

--
-- Name: ingest_rejects id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ingest_rejects ALTER COLUMN id SET DEFAULT nextval('public.ingest_rejects_id_seq'::regclass);

--
-- Name: job_runs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.job_runs ALTER COLUMN id SET DEFAULT nextval('public.job_runs_id_seq'::regclass);

--
-- Name: login_attempts id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.login_attempts ALTER COLUMN id SET DEFAULT nextval('public.login_attempts_id_seq'::regclass);

--
-- Name: oauth_identities id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.oauth_identities ALTER COLUMN id SET DEFAULT nextval('public.oauth_identities_id_seq'::regclass);

--
-- Name: sessions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sessions ALTER COLUMN id SET DEFAULT nextval('public.sessions_id_seq'::regclass);

--
-- Name: users id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users ALTER COLUMN id SET DEFAULT nextval('public.users_id_seq'::regclass);

--
-- Name: api_keys api_keys_key_hash_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_keys
    ADD CONSTRAINT api_keys_key_hash_key UNIQUE (key_hash);

--
-- Name: api_keys api_keys_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_keys
    ADD CONSTRAINT api_keys_pkey PRIMARY KEY (id);

--
-- Name: audit_log audit_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_log
    ADD CONSTRAINT audit_log_pkey PRIMARY KEY (id);

--
-- Name: auth_tokens auth_tokens_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_tokens
    ADD CONSTRAINT auth_tokens_pkey PRIMARY KEY (id);

--
-- Name: auth_tokens auth_tokens_token_hash_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_tokens
    ADD CONSTRAINT auth_tokens_token_hash_key UNIQUE (token_hash);

--
-- Name: caller_verifications caller_verifications_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.caller_verifications
    ADD CONSTRAINT caller_verifications_pkey PRIMARY KEY (id);

--
-- Name: callers callers_handle_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.callers
    ADD CONSTRAINT callers_handle_key UNIQUE (handle);

--
-- Name: callers callers_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.callers
    ADD CONSTRAINT callers_pkey PRIMARY KEY (id);

--
-- Name: calls calls_caller_id_seq_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.calls
    ADD CONSTRAINT calls_caller_id_seq_key UNIQUE (caller_id, seq);

--
-- Name: calls calls_content_hash_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.calls
    ADD CONSTRAINT calls_content_hash_key UNIQUE (content_hash);

--
-- Name: calls calls_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.calls
    ADD CONSTRAINT calls_pkey PRIMARY KEY (id);

--
-- Name: feature_flags feature_flags_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.feature_flags
    ADD CONSTRAINT feature_flags_pkey PRIMARY KEY (name);

--
-- Name: feed_health feed_health_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.feed_health
    ADD CONSTRAINT feed_health_pkey PRIMARY KEY (source);

--
-- Name: ingest_rejects ingest_rejects_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ingest_rejects
    ADD CONSTRAINT ingest_rejects_pkey PRIMARY KEY (id);

--
-- Name: invites invites_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.invites
    ADD CONSTRAINT invites_pkey PRIMARY KEY (code);

--
-- Name: job_runs job_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.job_runs
    ADD CONSTRAINT job_runs_pkey PRIMARY KEY (id);

--
-- Name: login_attempts login_attempts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.login_attempts
    ADD CONSTRAINT login_attempts_pkey PRIMARY KEY (id);

--
-- Name: oauth_identities oauth_identities_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.oauth_identities
    ADD CONSTRAINT oauth_identities_pkey PRIMARY KEY (id);

--
-- Name: oauth_identities oauth_identities_provider_subject_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.oauth_identities
    ADD CONSTRAINT oauth_identities_provider_subject_key UNIQUE (provider, subject);

--
-- Name: oauth_states oauth_states_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.oauth_states
    ADD CONSTRAINT oauth_states_pkey PRIMARY KEY (state);

--
-- Name: prices_eod prices_eod_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.prices_eod
    ADD CONSTRAINT prices_eod_pkey PRIMARY KEY (symbol, day);

--
-- Name: schema_migrations schema_migrations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.schema_migrations
    ADD CONSTRAINT schema_migrations_pkey PRIMARY KEY (version);

--
-- Name: sessions sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sessions
    ADD CONSTRAINT sessions_pkey PRIMARY KEY (id);

--
-- Name: sessions sessions_token_hash_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sessions
    ADD CONSTRAINT sessions_token_hash_key UNIQUE (token_hash);

--
-- Name: subscriptions subscriptions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.subscriptions
    ADD CONSTRAINT subscriptions_pkey PRIMARY KEY (user_id);

--
-- Name: users users_email_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_email_key UNIQUE (email);

--
-- Name: users users_handle_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_handle_key UNIQUE (handle);

--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);

--
-- Name: users users_referral_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_referral_code_key UNIQUE (referral_code);

--
-- Name: auth_tokens_expiry_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX auth_tokens_expiry_idx ON public.auth_tokens USING btree (expires_at);

--
-- Name: auth_tokens_user_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX auth_tokens_user_idx ON public.auth_tokens USING btree (user_id, purpose);

--
-- Name: caller_verifications_caller_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX caller_verifications_caller_idx ON public.caller_verifications USING btree (caller_id, created_at DESC);

--
-- Name: callers_one_per_user_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX callers_one_per_user_idx ON public.callers USING btree (user_id) WHERE (user_id IS NOT NULL);

--
-- Name: calls_due_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX calls_due_idx ON public.calls USING btree (published_at) WHERE (verdict IS NULL);

--
-- Name: idx_api_keys_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_api_keys_user ON public.api_keys USING btree (user_id);

--
-- Name: idx_login_attempts; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_login_attempts ON public.login_attempts USING btree (key, at);

--
-- Name: idx_prices_symbol_day; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_prices_symbol_day ON public.prices_eod USING btree (symbol, day);

--
-- Name: idx_sessions_token; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sessions_token ON public.sessions USING btree (token_hash);

--
-- Name: job_runs_job_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX job_runs_job_idx ON public.job_runs USING btree (job, started_at DESC);

--
-- Name: oauth_identities_user_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX oauth_identities_user_idx ON public.oauth_identities USING btree (user_id);

--
-- Name: audit_log audit_log_immutable; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER audit_log_immutable BEFORE DELETE OR UPDATE ON public.audit_log FOR EACH ROW EXECUTE FUNCTION public.forbid_mutation();

--
-- Name: callers callers_handle_immutable_trg; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER callers_handle_immutable_trg BEFORE UPDATE ON public.callers FOR EACH ROW EXECUTE FUNCTION public.callers_handle_immutable();

--
-- Name: calls calls_append_only_trg; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER calls_append_only_trg BEFORE DELETE OR UPDATE ON public.calls FOR EACH ROW EXECUTE FUNCTION public.calls_append_only();

--
-- Name: api_keys api_keys_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_keys
    ADD CONSTRAINT api_keys_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

--
-- Name: auth_tokens auth_tokens_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_tokens
    ADD CONSTRAINT auth_tokens_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

--
-- Name: caller_verifications caller_verifications_caller_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.caller_verifications
    ADD CONSTRAINT caller_verifications_caller_id_fkey FOREIGN KEY (caller_id) REFERENCES public.callers(id) ON DELETE CASCADE;

--
-- Name: callers callers_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.callers
    ADD CONSTRAINT callers_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE SET NULL;

--
-- Name: calls calls_caller_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.calls
    ADD CONSTRAINT calls_caller_id_fkey FOREIGN KEY (caller_id) REFERENCES public.callers(id);

--
-- Name: invites invites_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.invites
    ADD CONSTRAINT invites_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);

--
-- Name: invites invites_used_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.invites
    ADD CONSTRAINT invites_used_by_fkey FOREIGN KEY (used_by) REFERENCES public.users(id);

--
-- Name: oauth_identities oauth_identities_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.oauth_identities
    ADD CONSTRAINT oauth_identities_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

--
-- Name: sessions sessions_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sessions
    ADD CONSTRAINT sessions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);

--
-- Name: subscriptions subscriptions_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.subscriptions
    ADD CONSTRAINT subscriptions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

--
-- Name: users users_referred_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_referred_by_fkey FOREIGN KEY (referred_by) REFERENCES public.users(id);


-- ------------------------------------------------------------------ the migrations this stands in for
--
-- 1..37 inclusive. Without these rows the runner would apply all 37 on top of this schema on the
-- very next `cli migrate`, and the first of them would fail on a table that already exists.

-- SCHEMA-QUALIFIED, and `search_path` restored first. pg_dump's preamble runs
-- `SELECT pg_catalog.set_config('search_path', '', false)` so that every object it creates is
-- written out fully qualified and cannot land in the wrong schema. That setting is still in force
-- down here, so a bare `schema_migrations` resolves to nothing and this file failed at its last
-- statement with "relation schema_migrations does not exist" — after creating all 19 tables.
SET search_path = public;

INSERT INTO public.schema_migrations (version)
SELECT generate_series(1, 37)
ON CONFLICT (version) DO NOTHING;
