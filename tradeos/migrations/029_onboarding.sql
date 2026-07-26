-- Migration 029: onboarding state (Phase 8).
--
-- Relevance scoring is worthless without a country, which is why the brief says onboarding exists
-- mainly to fill `user_profiles` in. `PUT /api/profile/frame` has been able to write that row since
-- Phase 3; nothing ever asked a new account for it, so almost every profile is empty and every
-- reader has been getting the unpersonalised ordering.
--
-- Two timestamps rather than a boolean, because "skippable but gently persistent" is a behaviour a
-- boolean cannot express:
--
--   onboarded_at    set once, when the reader actually completes it. Never cleared.
--   snoozed_until   set when they dismiss it. The prompt returns afterwards rather than never.
--
-- A reader who has completed it is never asked again. A reader who skipped is asked again later,
-- and can keep skipping forever — that is the point of "gently". Neither field gates any feature;
-- the product works fully without a frame, it just cannot rank for you.

ALTER TABLE user_profiles ADD COLUMN onboarded_at  timestamptz;
ALTER TABLE user_profiles ADD COLUMN snoozed_until timestamptz;

-- Existing profiles predate onboarding and already carry a country, so they are complete by
-- definition. Backfilling them prevents asking established readers to redo what they have done.
UPDATE user_profiles SET onboarded_at = updated_at WHERE country IS NOT NULL;

INSERT INTO schema_migrations (version) VALUES (29);
