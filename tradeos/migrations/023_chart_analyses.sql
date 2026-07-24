-- TradeOS migration 023: AI chart-analysis cache (Milestone 6).
-- A user uploads a screenshot of their OWN trade/chart; the interpretive plane reads it into an
-- EDUCATIONAL analysis (visible pattern, structure, risk/reward, coaching observations) — guarded so it
-- describes and teaches, never advises. Vision calls are expensive, so the result is cached per trade
-- and invalidated by the image's hash (re-analyzed only when the user uploads a new screenshot).

CREATE TABLE chart_analyses (
    trade_id      bigint PRIMARY KEY REFERENCES trades(id) ON DELETE CASCADE,
    image_hash    char(64) NOT NULL,
    analysis      jsonb NOT NULL,
    model_id      text NOT NULL,
    used_template boolean NOT NULL,     -- true = deterministic fallback (no vision model / guard trip)
    created_at    timestamptz NOT NULL DEFAULT now()
);

INSERT INTO schema_migrations (version) VALUES (23);
