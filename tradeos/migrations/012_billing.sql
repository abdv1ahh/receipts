-- TradeOS migration 012: subscriptions, billing audit, and Pro-tier API keys (game-changer Slice D).
-- Card data never touches these tables — Stripe holds it. We store only the subscription state and a
-- signature-verified, idempotent audit of every billing event. API keys are stored hashed (never raw)
-- with a per-key canary so a resold dataset is traceable to the key that leaked it.

CREATE TABLE subscriptions (
    user_id                  bigint PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    plan                     text NOT NULL DEFAULT 'free' CHECK (plan IN ('free','retail','pro')),
    status                   text NOT NULL DEFAULT 'active' CHECK (status IN ('active','past_due','canceled','trialing')),
    provider                 text,                    -- 'stripe' | 'test'
    provider_customer_id     text,
    provider_subscription_id text,
    current_period_end       timestamptz,
    updated_at               timestamptz NOT NULL DEFAULT now(),
    created_at               timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE billing_events (
    id                bigserial PRIMARY KEY,
    user_id           bigint REFERENCES users(id) ON DELETE SET NULL,
    provider          text NOT NULL,
    event_type        text NOT NULL,
    provider_event_id text UNIQUE,                    -- webhook idempotency key
    payload           jsonb,
    at                timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE api_keys (
    id           bigserial PRIMARY KEY,
    user_id      bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name         text,
    prefix       text NOT NULL,                       -- first chars, shown in the UI
    key_hash     char(64) NOT NULL UNIQUE,            -- sha256 of the full key; raw key never stored
    scopes       text[] NOT NULL DEFAULT '{read}',
    canary       text NOT NULL,                       -- per-key tracer seed (see docs/threat-models/billing.md)
    last_used_at timestamptz,
    created_at   timestamptz NOT NULL DEFAULT now(),
    revoked_at   timestamptz
);
CREATE INDEX idx_api_keys_user ON api_keys (user_id);

INSERT INTO schema_migrations (version) VALUES (12);
