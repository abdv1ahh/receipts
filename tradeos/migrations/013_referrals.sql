-- TradeOS migration 013: referral growth loop (game-changer follow-up).
-- A reusable per-user referral code turns the invite gate into a growth loop: a referral code is
-- accepted as a valid invite at registration, the new user is linked to their referrer, and the
-- reward (a 14-day Pro trial) is a real trialing subscription whose expiry is enforced lazily on
-- read (authn.session_user), so it can never become free-Pro-forever without a running cron.

ALTER TABLE users ADD COLUMN referral_code text UNIQUE;
ALTER TABLE users ADD COLUMN referred_by  bigint REFERENCES users(id);

INSERT INTO schema_migrations (version) VALUES (13);
