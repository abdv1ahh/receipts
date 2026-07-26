-- Migration 030: OAuth identities (Phase 8).
--
-- Linked by the provider's SUBJECT, never by email. An email address is mutable and reassignable —
-- a corporate mailbox can be handed to a new employee — so matching on it means a new person can
-- inherit an old person's account. `sub` is stable and unique for the life of the provider account,
-- which is exactly the property needed here.
--
-- `email` is stored anyway, but only as a record of what the provider asserted at link time. It is
-- never the lookup key.
--
-- One row per (provider, subject). A single user may hold several identities — a Google login and,
-- later, another provider — which is why user_id is not unique.

CREATE TABLE oauth_identities (
    id         bigserial PRIMARY KEY,
    provider   text   NOT NULL,                  -- 'google'
    subject    text   NOT NULL,                  -- the provider's stable user id ("sub")
    user_id    bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    email      text,                             -- what the provider asserted, for the record only
    linked_at  timestamptz NOT NULL DEFAULT now(),
    last_login timestamptz,
    UNIQUE (provider, subject)
);

CREATE INDEX oauth_identities_user_idx ON oauth_identities (user_id);


-- The one-time state value for the authorization-code flow. Server-side rather than a signed
-- cookie, because it has to be *consumed* — a state that can be replayed is not CSRF protection,
-- and the only way to guarantee single use is to delete the row and check that a row was deleted.
CREATE TABLE oauth_states (
    state       text PRIMARY KEY,
    provider    text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    redirect_to text                             -- where to send the browser after success
);

INSERT INTO schema_migrations (version) VALUES (30);
