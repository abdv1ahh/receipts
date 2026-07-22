-- TradeOS migration 010: follows, alert preferences, in-app notifications, email outbox
-- (game-changer Slice B: the product reaches out). Additive.
--
-- The alert engine writes notifications idempotently, keyed on (user_id, dedup_key), so re-running
-- it never double-notifies. Email is provider-agnostic: rows land in email_outbox as 'queued' and
-- are marked 'sent' only when a real provider delivers them. No provider is configured in the demo,
-- so email honestly stays queued (never a fake "sent"). In-app notifications are the working channel.

CREATE TABLE follows (
    id         bigserial PRIMARY KEY,
    user_id    bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind       text NOT NULL CHECK (kind IN ('symbol','insider','filer')),
    ref        text NOT NULL,                 -- symbol | owner_cik | filer entity_id (as text)
    label      text,                          -- display name captured at follow time
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (user_id, kind, ref)
);
CREATE INDEX idx_follows_user ON follows (user_id);

CREATE TABLE alert_prefs (
    user_id             bigint PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    new_high_conviction boolean NOT NULL DEFAULT true,   -- any new convergence at/above min_score
    followed_activity   boolean NOT NULL DEFAULT true,   -- a followed name / person / fund moves
    min_score           int NOT NULL DEFAULT 75 CHECK (min_score BETWEEN 0 AND 100),
    email_enabled       boolean NOT NULL DEFAULT false,  -- queue a digest email (needs a provider)
    updated_at          timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE notifications (
    id         bigserial PRIMARY KEY,
    user_id    bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind       text NOT NULL,                 -- high_conviction | followed_symbol | followed_actor
    title      text NOT NULL,
    body       text NOT NULL,
    symbol     text,                          -- subject ticker, when there is one
    entity_id  bigint,                        -- subject issuer entity, when there is one
    dedup_key  text NOT NULL,                 -- stable per event -> exactly-once per user
    created_at timestamptz NOT NULL DEFAULT now(),
    read_at    timestamptz,
    UNIQUE (user_id, dedup_key)
);
CREATE INDEX idx_notifications_user ON notifications (user_id, created_at DESC);

CREATE TABLE email_outbox (
    id         bigserial PRIMARY KEY,
    user_id    bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    to_email   text NOT NULL,
    subject    text NOT NULL,
    body       text NOT NULL,
    status     text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','sent','failed','skipped')),
    provider   text,
    created_at timestamptz NOT NULL DEFAULT now(),
    sent_at    timestamptz
);
CREATE INDEX idx_email_outbox_status ON email_outbox (status, created_at);

INSERT INTO schema_migrations (version) VALUES (10);
