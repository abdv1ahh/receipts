-- Migration 034: Receipts — a permanent, chained, public record of market calls.
--
-- WHAT THIS IS FOR. Everything else in this database is an observation: a filing arrived, a price
-- moved, a model wrote a sentence. This is the first table that holds a COMMITMENT — a named
-- person or algorithm saying, before the outcome was known, that a specific instrument would go a
-- specific way over a specific window. The value of that record is entirely in its being
-- unchangeable, so the integrity constraints below are not a safeguard around the feature. They
-- ARE the feature. A record whose owner can quietly drop a loser is a marketing page.
--
-- Three mechanisms hold it, and each one closes a different hole:
--
--   the hash chain      every call carries the hash of the one before it, so removing, reordering
--                       or rewriting any call breaks every hash after it. Anyone can recompute
--                       the whole chain from the published fields and check.
--   the trigger         the database itself refuses a DELETE and refuses an UPDATE to any sealed
--                       column. Application code can be wrong; this cannot be bypassed by it.
--   knowable_time       written at publish and never after, so a backtest and a reader see the
--                       same thing: the call as it stood before its outcome existed.
--
-- Be precise about what the chain proves, because overclaiming here would cost more credibility
-- than it buys. It is tamper evident against the CALLER. It is not tamper evident against the
-- OPERATOR of this database, who could recompute every hash after rewriting history. Making that
-- impossible needs an external anchor — publishing the chain head somewhere the operator does not
-- control — and that is deliberately not built yet. The methodology page says so in those words.

-- ---------------------------------------------------------------------------------------------
-- CALLERS. A caller is a named record-holder, not a user account: the two are related but they
-- are not the same thing, and conflating them would mean a record dies with a login.
--
-- `user_id` is therefore nullable with ON DELETE SET NULL. The two algorithm callers seeded from
-- our own signal engine have no user at all, and a human deleting their account must not take a
-- published record with them — that would be exactly the delete path the whole design refuses.
CREATE TABLE callers (
    id                        bigserial PRIMARY KEY,
    user_id                   bigint REFERENCES users(id) ON DELETE SET NULL,
    handle                    text NOT NULL UNIQUE,
    display_name              text NOT NULL,
    bio                       text,
    -- 'algorithm' is not decoration. A reader judging a record is entitled to know whether they
    -- are reading a person's judgement or a scoring function's output, and our own two records
    -- are the latter.
    kind                      text NOT NULL DEFAULT 'human'
                                  CHECK (kind IN ('human', 'algorithm')),
    is_house                  boolean NOT NULL DEFAULT false,
    audience_url              text,
    verified_at               timestamptz,
    verification_method       text CHECK (verification_method IN
                                  ('public_post', 'meta_tag', 'wallet_signature', 'house')),
    verification_evidence_url text,
    -- Regulatory posture, stored rather than assumed. This platform measures public statements; it
    -- does not license anybody to make them. A caller attests that their own registration status
    -- in their own jurisdiction is their responsibility, and a caller cannot be created without
    -- it. See docs and the disclaimer copy for why this is a column and not a paragraph.
    jurisdiction_attested     boolean NOT NULL DEFAULT false,
    created_at                timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------------------------
-- CALLS. The sealed columns are everything above `entry_session`; the resolution columns below it
-- are the only fields any later write may touch, and the trigger enforces exactly that boundary.
--
-- `published_at` and `knowable_time` are both stored and are set to the same instant at publish.
-- They are not redundant: the rest of this codebase treats knowable_time as "the first moment this
-- information could have been acted on", and every point-in-time query in the product reads that
-- name. Keeping the name here means a call joins the same discipline as a filing, rather than
-- being a special case someone has to remember.
CREATE TABLE calls (
    id                bigserial PRIMARY KEY,
    caller_id         bigint NOT NULL REFERENCES callers(id),
    seq               integer NOT NULL,
    symbol            text NOT NULL,
    direction         text NOT NULL CHECK (direction IN ('up', 'down')),
    -- Three horizons, not free text. A record where every caller picks their own window cannot be
    -- compared across callers, and the point of a board is comparison.
    horizon_days      integer NOT NULL CHECK (horizon_days IN (7, 30, 90)),
    confidence        text NOT NULL CHECK (confidence IN ('low', 'medium', 'high')),
    thesis            text NOT NULL,
    benchmark_symbol  text NOT NULL DEFAULT 'SPY',
    published_at      timestamptz NOT NULL,
    knowable_time     timestamptz NOT NULL,
    prev_hash         text NOT NULL,
    content_hash      text NOT NULL,

    -- ---- resolution columns: NULL until the horizon elapses, written once by the scorer -------
    entry_session     date,
    exit_session      date,
    entry_price       numeric,
    exit_price        numeric,
    benchmark_entry   numeric,
    benchmark_exit    numeric,
    subject_return    numeric,
    benchmark_return  numeric,
    excess_return     numeric,
    verdict           text CHECK (verdict IN ('hit', 'miss', 'inconclusive', 'unscoreable')),
    verdict_note      text,
    resolved_at       timestamptz,
    -- What the system itself was showing at the moment this call was published: which
    -- interpretations were live on this symbol, whether any of them pointed the other way. Frozen
    -- here so it cannot be reconstructed favourably afterwards. Same substrate the journal uses.
    context_snapshot  jsonb,

    UNIQUE (caller_id, seq),
    UNIQUE (content_hash)
);

-- The UNIQUE (caller_id, seq) constraint above already builds a btree on exactly (caller_id, seq),
-- which is the index every chain walk and every record page needs, so no second copy is created
-- here. A duplicate index is not free: it is another write on every insert and one more thing to
-- keep in step.

-- The resolver's work queue. `verdict IS NULL` is the partial predicate, so `verdict` itself
-- carries no information inside the index and only `published_at` belongs in the key.
CREATE INDEX calls_due_idx ON calls (published_at) WHERE verdict IS NULL;

-- ---------------------------------------------------------------------------------------------
-- VERIFICATIONS. A caller proves they control the place their audience already is — a newsletter,
-- a site, a public post — by publishing a one-time code there. Free, no third-party API, and
-- reviewable by a human, which is the right shape while the volume is small.
CREATE TABLE caller_verifications (
    id           bigserial PRIMARY KEY,
    caller_id    bigint NOT NULL REFERENCES callers(id) ON DELETE CASCADE,
    code         text NOT NULL,
    method       text NOT NULL,
    evidence_url text,
    status       text NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending', 'confirmed', 'rejected')),
    created_at   timestamptz NOT NULL DEFAULT now(),
    resolved_at  timestamptz
);

CREATE INDEX caller_verifications_caller_idx ON caller_verifications (caller_id, created_at DESC);

-- ---------------------------------------------------------------------------------------------
-- THE APPEND-ONLY TRIGGER. The single most important object in this migration.
--
-- Put in the DATABASE rather than in the application on purpose. Application-level immutability is
-- a promise that every future code path has to keep, including the admin tool nobody has written
-- yet and the psql session someone opens at 2am. This one is kept by Postgres, for every
-- connection, including mine.
--
-- Note what it deliberately DOES allow: writing the resolution columns once, and only once for the
-- verdict. Scoring has to be able to happen after publication or nothing could ever be scored. The
-- boundary is drawn at exactly the fields a caller could use to flatter their record.
CREATE OR REPLACE FUNCTION calls_append_only() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'calls rows are append only and cannot be deleted';
    END IF;

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
    OR OLD.benchmark_symbol IS DISTINCT FROM NEW.benchmark_symbol THEN
        RAISE EXCEPTION 'sealed columns on calls are immutable';
    END IF;

    -- A verdict is written once. Re-scoring a resolved call is how a miss would become a hit, so
    -- a correction to the scorer produces a new measurement everywhere EXCEPT here, and a genuine
    -- scoring error has to be disclosed rather than overwritten.
    IF OLD.verdict IS NOT NULL AND OLD.verdict IS DISTINCT FROM NEW.verdict THEN
        RAISE EXCEPTION 'a resolved verdict cannot be changed';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER calls_append_only_trg
    BEFORE UPDATE OR DELETE ON calls
    FOR EACH ROW EXECUTE FUNCTION calls_append_only();

-- callers has no such trigger and does not need one: calls.caller_id has no ON DELETE clause, so
-- Postgres's default NO ACTION already refuses to delete any caller who has ever published. A
-- caller with a record cannot be removed, and one with no record has nothing to protect.

INSERT INTO schema_migrations (version) VALUES (34);
