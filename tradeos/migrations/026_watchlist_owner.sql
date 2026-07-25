-- Migration 026: give the watchlist a real owner (bug B-22).
--
-- `watchlists` was keyed by `user_key text NOT NULL DEFAULT 'demo'` — a free-text key, not a
-- foreign key to users — and its routes took that key as a QUERY PARAMETER with no session check.
-- So every account read and wrote the same 'demo' list, and any caller could address any other
-- key by changing one parameter. The table predates real accounts.
--
-- This adds a proper owner column, migrates what can be attributed, and leaves the rest visible
-- rather than silently deleting anyone's data. `user_key` is kept (nullable) for one release so a
-- rollback does not lose the mapping; a later migration drops it.

ALTER TABLE watchlists ADD COLUMN user_id bigint REFERENCES users(id) ON DELETE CASCADE;

-- Rows whose key is already a user id, or an email that resolves to one, are attributed.
UPDATE watchlists w SET user_id = u.id
  FROM users u
 WHERE w.user_id IS NULL
   AND (w.user_key = u.id::text OR lower(w.user_key) = lower(u.email));

-- The shared 'demo' pile belongs to the seeded demo account when it exists. Everything else is
-- left unattributed and simply stops being served — it was never anyone's in particular, and
-- guessing an owner would be worse than showing an empty list.
UPDATE watchlists w SET user_id = u.id
  FROM users u
 WHERE w.user_id IS NULL AND w.user_key = 'demo' AND u.email = 'demo@tradeos.app';

ALTER TABLE watchlists ALTER COLUMN user_key DROP NOT NULL;
ALTER TABLE watchlists ALTER COLUMN user_key DROP DEFAULT;

-- Uniqueness now belongs to the owner, not the free-text key.
ALTER TABLE watchlists DROP CONSTRAINT IF EXISTS watchlists_user_key_symbol_key;
CREATE UNIQUE INDEX IF NOT EXISTS watchlists_owner_symbol_idx ON watchlists (user_id, symbol);
CREATE INDEX IF NOT EXISTS watchlists_owner_idx ON watchlists (user_id);

INSERT INTO schema_migrations (version) VALUES (26);
