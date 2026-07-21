-- TradeOS migration 016: community & social graph (Slice F).
-- Public trades (Slice E) become social: a handle-based identity, follows between traders, reactions,
-- comments, and report/auto-hide moderation. The focus stays on learning — the trader leaderboard
-- (in code) ranks by an honest win rate above a sample floor, never a raw-return number that would
-- invite fabrication or pumping. All UGC is length-capped + React-escaped + object-level authorized.

ALTER TABLE users ADD COLUMN handle citext UNIQUE;   -- public identity; NULL until the user claims one
ALTER TABLE users ADD COLUMN bio text;
ALTER TABLE trades ADD COLUMN hidden boolean NOT NULL DEFAULT false;  -- moderation (report auto-hide)

CREATE TABLE user_follows (
    follower_id bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    followee_id bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (follower_id, followee_id),
    CHECK (follower_id <> followee_id)
);
CREATE INDEX idx_user_follows_followee ON user_follows (followee_id);

CREATE TABLE trade_reactions (
    id         bigserial PRIMARY KEY,
    trade_id   bigint NOT NULL REFERENCES trades(id) ON DELETE CASCADE,
    user_id    bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind       text NOT NULL CHECK (kind IN ('like','save')),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (trade_id, user_id, kind)
);
CREATE INDEX idx_reactions_trade ON trade_reactions (trade_id, kind);
CREATE INDEX idx_reactions_user_save ON trade_reactions (user_id) WHERE kind = 'save';

CREATE TABLE trade_comments (
    id         bigserial PRIMARY KEY,
    trade_id   bigint NOT NULL REFERENCES trades(id) ON DELETE CASCADE,
    user_id    bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    body       text NOT NULL,
    hidden     boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_comments_trade ON trade_comments (trade_id, created_at);

CREATE TABLE content_reports (
    id          bigserial PRIMARY KEY,
    reporter_id bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    target_type text NOT NULL CHECK (target_type IN ('trade','comment')),
    target_id   bigint NOT NULL,
    reason      text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (reporter_id, target_type, target_id)   -- one report per user per target
);
CREATE INDEX idx_reports_target ON content_reports (target_type, target_id);

INSERT INTO schema_migrations (version) VALUES (16);
