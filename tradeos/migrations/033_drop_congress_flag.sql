-- 033: remove the congress feature-flag row.
--
-- Migration 009 seeded a `congress` flag to gate congressional-trading disclosures as a signal
-- input. The source was never built — decision #29 recorded that there is no clean structured
-- primary source for it — so the flag has always gated nothing, and its env twin ENABLE_CONGRESS
-- is removed from config.py in the same change. The reasoning stays in docs/decision-log.md, which
-- is where a decision belongs; a live switch for a feature that does not exist is just something
-- for a future reader to misinterpret.
--
-- Deliberately NOT dropping short_interest: that one is parked on purpose (ingested and stored,
-- awaiting a convergence-score version bump), and the owner confirmed on 2026-07-26 to keep it.

DELETE FROM feature_flags WHERE name = 'congress';

INSERT INTO schema_migrations (version) VALUES (33);
