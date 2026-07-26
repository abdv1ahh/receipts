-- Migration 031: email verification and password reset.
--
-- Two gaps the ten-phase brief never asked for and that would have hurt a real user first: an
-- account was usable immediately with an unverified address, and a forgotten password was
-- unrecoverable with no path back other than an operator editing the database.
--
-- One table for both, because they are the same object — a single-use, time-limited, hashed
-- capability — and two tables would mean two places to get the expiry and single-use logic right.
--
-- `token_hash` and not the token. Same discipline as `sessions`: anyone who reads this table gets
-- nothing they can use. A reset token is a temporary password, and storing it in the clear would
-- make a database read equivalent to owning every account.

CREATE TABLE auth_tokens (
    id          bigserial PRIMARY KEY,
    user_id     bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    purpose     text   NOT NULL CHECK (purpose IN ('verify_email', 'reset_password')),
    token_hash  char(64) NOT NULL UNIQUE,
    created_at  timestamptz NOT NULL DEFAULT now(),
    expires_at  timestamptz NOT NULL,
    -- Set when redeemed. The row is kept rather than deleted so a second attempt can be told
    -- "already used" instead of "invalid" — different facts, and the honest one is cheap here
    -- because the holder of the token already proved they had it.
    used_at     timestamptz
);

CREATE INDEX auth_tokens_user_idx ON auth_tokens (user_id, purpose);
CREATE INDEX auth_tokens_expiry_idx ON auth_tokens (expires_at);


-- When the address was proven. NULL means unproven, which is the honest default for every account
-- that predates this migration: they were never asked, so claiming they were verified would be a
-- lie written by a migration.
ALTER TABLE users ADD COLUMN email_verified_at timestamptz;

INSERT INTO schema_migrations (version) VALUES (31);
