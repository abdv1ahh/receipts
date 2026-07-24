-- TradeOS migration 021: scheduler job-run log (Milestone 3, continuous updates).
-- The worker records every job attempt here, so freshness is observable and a degrading job degrades
-- LOUDLY (same honesty rule as feed_health / ingest_rejects) rather than silently going stale. The
-- last successful run per job also drives the scheduler's own due-logic, so it survives a restart.

CREATE TABLE job_runs (
    id          bigserial PRIMARY KEY,
    job         text NOT NULL,
    started_at  timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    status      text,                 -- 'ok' | 'error'
    detail      jsonb,                -- counters on success, error type/message on failure
    duration_ms integer
);
CREATE INDEX job_runs_job_idx ON job_runs (job, started_at DESC);

INSERT INTO schema_migrations (version) VALUES (21);
