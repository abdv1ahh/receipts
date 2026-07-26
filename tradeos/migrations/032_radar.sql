-- Migration 032: threading and saved filter sets (the Phase 4 remainder).
--
-- Two things the brief asked for in Phase 4 and that were carried as outstanding ever since.

-- ---------------------------------------------------------------------------------------------
-- THREADING. "When an event develops over days, the card updates in place with a visible history
-- of how the interpretation changed... Users should be able to watch the system change its mind
-- and see why."
--
-- The substrate already existed: events cluster, and 39 clusters have gained sources after their
-- first claim was made. What was missing is that `interpret` skipped any cluster that already had
-- a claim, so a story that developed never got a second reading and there was nothing to thread.
--
-- `supersedes` links a revision to what it revised. A thread is then a chain, newest first.
--
-- THE RULE THAT MAKES THIS HONEST: a superseded claim is still scored. It is not withdrawn, not
-- excluded from the Ledger, and not marked unscoreable. It was a real commitment, live for a real
-- period, and it gets marked against what actually happened. If revising removed a claim from the
-- record, "changing its mind" would be a mechanism for erasing misses, and the Ledger — the one
-- number this product is built on — would become editable by writing a better guess afterwards.
ALTER TABLE claims ADD COLUMN supersedes bigint REFERENCES claims(id) ON DELETE SET NULL;
CREATE INDEX claims_supersedes_idx ON claims (supersedes) WHERE supersedes IS NOT NULL;


-- ---------------------------------------------------------------------------------------------
-- SAVED FILTER SETS, and subscriptions on them. "A user watching Gulf energy policy and one
-- watching crypto regulation want entirely different streams."
CREATE TABLE radar_filters (
    id            bigserial PRIMARY KEY,
    user_id       bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name          text NOT NULL,
    -- {categories:[], geo:[], horizons:[], sources:[], min_confidence: 0.0}
    -- jsonb rather than columns: the filter dimensions are a product decision that has already
    -- changed once, and a migration per dimension is the wrong trade for a per-user preference.
    spec          jsonb NOT NULL DEFAULT '{}',

    -- subscription. Off by default — a saved filter is a view, and turning a view into email is a
    -- separate decision the user makes deliberately.
    subscribed    boolean NOT NULL DEFAULT false,
    channel       text CHECK (channel IN ('email', 'webhook')),
    webhook_url   text,
    -- "throttled hard so they never become noise". Six hours by default, one hour floor, enforced
    -- server-side; a client cannot ask to be notified more often than this.
    throttle_mins int NOT NULL DEFAULT 360 CHECK (throttle_mins >= 60),

    -- High-water mark. Delivery reports claims strictly newer than this, so a retry, a restart or
    -- a clock change can never resend something already sent.
    last_claim_id bigint,
    last_sent_at  timestamptz,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (user_id, name)
);

CREATE INDEX radar_filters_due_idx ON radar_filters (subscribed, last_sent_at) WHERE subscribed;

INSERT INTO schema_migrations (version) VALUES (32);
