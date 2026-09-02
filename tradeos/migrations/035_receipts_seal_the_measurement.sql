-- Migration 035: close two holes in the Receipts integrity guarantee that 034 left open.
--
-- Found by /code-review on the branch that added 034. Both are in the same class: a guarantee the
-- documentation states and the schema did not actually enforce.
--
-- ---------------------------------------------------------------------------------------------
-- HOLE 1. THE ARITHMETIC WAS NOT PROTECTED, ONLY THE VERDICT.
--
-- 034's trigger sealed the commitment and refused to change a verdict once written. It said
-- nothing about the nine columns the verdict is COMPUTED from, so this succeeded:
--
--     UPDATE calls SET excess_return = 0.42 WHERE verdict = 'miss';
--
-- The verdict still reads 'miss', every hash still verifies — none of these are sealed fields —
-- and the published expectancy, the confidence interval and every proof panel have all moved. The
-- record would show a miss whose arithmetic says it was a win, and the page whose entire argument
-- is "check the numbers yourself" would be showing numbers that had been edited.
--
-- `context_snapshot` had the same problem while 034 described it, three lines above the trigger,
-- as "Frozen here so it cannot be reconstructed favourably afterwards". It was not frozen.
--
-- THE RULE NOW: a call is written once and scored once.
--
--   before resolution   only the resolution columns may be filled in, and context_snapshot is
--                       already fixed from insert
--   after resolution    nothing may change at all
--
-- `resolved_at` is the switch, and it is set in the same statement that writes the verdict.
--
-- ---------------------------------------------------------------------------------------------
-- HOLE 2. A USER COULD END UP HOLDING TWO CALLER ROWS.
--
-- `claim_handle` guards with a SELECT and then INSERTs, and nothing in the schema backed that up:
-- `callers.user_id` had no unique constraint, and two concurrent posts (a double click, a retried
-- request) both pass the guard and both insert under different handles, so `UNIQUE (handle)` does
-- not catch it. `_caller_for_user` then returns whichever row the planner happens to yield, so
-- "my record", "publish under" and verification could each land on a different one between
-- requests. A partial unique index makes the database refuse the second row.
--
-- Partial, because `user_id` is nullable on purpose: the two house callers have no user at all,
-- and a human deleting their account sets it to NULL rather than taking a published record with
-- them. A plain UNIQUE would allow only one such row in the whole table.

CREATE UNIQUE INDEX callers_one_per_user_idx ON callers (user_id) WHERE user_id IS NOT NULL;

CREATE OR REPLACE FUNCTION calls_append_only() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'calls rows are append only and cannot be deleted';
    END IF;

    -- The commitment. Unchanged from 034; these are exactly the fields the hash covers, plus the
    -- frozen context, which is now here rather than only in a comment.
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

    -- The measurement. Once a call has been scored, every figure the verdict rests on is frozen
    -- with it. A correction to the scorer therefore has to be disclosed rather than applied
    -- quietly, which binds us as much as it binds a caller, and is the point.
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
        OR OLD.excess_return    IS DISTINCT FROM NEW.excess_return THEN
            RAISE EXCEPTION 'a resolved call is immutable, including the figures it was scored on';
        END IF;
    END IF;

    -- A verdict without a resolved_at would sidestep the block above entirely, so the two are
    -- required to travel together. `receipts.scoring._write` sets both in one statement.
    IF NEW.verdict IS NOT NULL AND NEW.resolved_at IS NULL THEN
        RAISE EXCEPTION 'a verdict must be written together with its resolved_at';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

INSERT INTO schema_migrations (version) VALUES (35);
