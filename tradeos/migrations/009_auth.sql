-- TradeOS migration 009: authentication, sessions, entitlements, audit, feature flags (Slice 6).
-- Additive. Session tokens are stored only as hashes; the audit log is append-only (same
-- immutability trigger as the raw layer). Tier drives the free-tier delay server-side.

CREATE EXTENSION IF NOT EXISTS citext;

CREATE TABLE users (
    id            bigserial PRIMARY KEY,
    email         citext UNIQUE NOT NULL,
    password_hash text NOT NULL,               -- argon2id
    tier          text NOT NULL DEFAULT 'free' CHECK (tier IN ('free','retail','pro','admin')),
    totp_secret   text,                          -- required for admin; optional otherwise
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE sessions (
    id         bigserial PRIMARY KEY,
    user_id    bigint NOT NULL REFERENCES users(id),
    token_hash char(64) NOT NULL UNIQUE,         -- sha256 of the cookie token; raw token never stored
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    ip         text,
    ua         text
);
CREATE INDEX idx_sessions_token ON sessions (token_hash);

CREATE TABLE invites (
    code       text PRIMARY KEY,
    created_by bigint REFERENCES users(id),
    used_by    bigint REFERENCES users(id),
    used_at    timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE audit_log (
    id     bigserial PRIMARY KEY,
    actor  text,
    action text NOT NULL,
    object text,
    at     timestamptz NOT NULL DEFAULT now(),
    detail jsonb
);
CREATE TRIGGER audit_log_immutable
    BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

CREATE TABLE login_attempts (
    id  bigserial PRIMARY KEY,
    key text NOT NULL,                           -- an IP or an email
    at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_login_attempts ON login_attempts (key, at);

-- geofence / feature gating hook (build-plan 7.2): flip a row, not a rebuild
CREATE TABLE feature_flags (
    name             text PRIMARY KEY,
    enabled          boolean NOT NULL DEFAULT true,
    blocked_countries text[] NOT NULL DEFAULT '{}'
);
INSERT INTO feature_flags (name, enabled) VALUES
    ('congress', false), ('short_interest', false), ('signals', true), ('previews', true);

INSERT INTO schema_migrations (version) VALUES (9);
