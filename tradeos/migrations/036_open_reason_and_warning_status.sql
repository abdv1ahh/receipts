-- Migration 036: say WHY a past-horizon call is still open, and let a job report a warning.
--
-- Both come out of the Part A proof run -- the first time this product's scorer scored calls this
-- product published. Twelve genuinely-due calls, eleven of them exactly right, and two defects
-- that only a real run could show.
--
-- ---------------------------------------------------------------------------------------------
-- 1. A CALL PAST ITS HORIZON THAT IS STILL OPEN TOLD A READER NOTHING.
--
-- `resolve_due` returned "4 call(s) reached their horizon but the price feed has not" and threw
-- that sentence away into a log line. On the row itself: verdict NULL, verdict_note NULL. So a
-- record page showed a call thirty days past its stated horizon with no verdict and no
-- explanation, which to a sceptic is indistinguishable from a result being withheld -- on the one
-- product whose entire argument is that nothing is withheld.
--
-- These three columns are the answer, and they are deliberately NOT sealed. The reason a call is
-- open is a LIVE FACT that changes as the feed catches up: "waiting for the benchmark" this
-- morning becomes "waiting for the subject" this afternoon and a verdict tomorrow. A commitment
-- is sealed; an observation about our own data is maintained. They are frozen at resolution along
-- with everything else, because a resolved call has no open reason -- `scoring._write` nulls them
-- in the same statement that writes the verdict.
ALTER TABLE calls ADD COLUMN open_reason_code text
    CHECK (open_reason_code IS NULL OR open_reason_code IN (
        'waiting_for_benchmark',      -- OUR gap: the benchmark lacks a session this call needs
        'waiting_for_subject_price',  -- the subject's feed is behind; it is expected to catch up
        'subject_series_ended'        -- the subject stopped trading long before the benchmark did
    ));
ALTER TABLE calls ADD COLUMN open_reason text;
ALTER TABLE calls ADD COLUMN open_checked_at timestamptz;

-- ---------------------------------------------------------------------------------------------
-- 2. A JOB THAT DID NONE OF ITS WORK WAS RECORDED EXACTLY LIKE ONE THAT SUCCEEDED.
--
-- `status` was 'ok' | 'error' in a comment and unconstrained in the schema. Part A measured
-- `run_job` returning status ok on a run that resolved 0 of 4 due calls. That is the same shape
-- as the failure this codebase already paid for once: five weeks of green while the claim engine
-- produced nothing, because "did not crash" and "did its job" were the same value.
--
-- The CHECK is added at the same time as the third state so the set of legal statuses stops being
-- a comment. Every existing row is 'ok' (measured: 3,096 rows, one distinct value).
ALTER TABLE job_runs ADD CONSTRAINT job_runs_status_known
    CHECK (status IS NULL OR status IN ('ok', 'warning', 'error'));

-- ---------------------------------------------------------------------------------------------
-- 3. THE TRIGGER, REPLACED TO COVER THE THREE NEW COLUMNS.
--
-- Unchanged from 035 except for the post-resolution list. Restated in full rather than patched,
-- because a trigger assembled from fragments across migrations is one nobody can read in one
-- sitting, and this function is the single most important object in the schema.
CREATE OR REPLACE FUNCTION calls_append_only() RETURNS trigger AS $$
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
$$ LANGUAGE plpgsql;

INSERT INTO schema_migrations (version) VALUES (36);
