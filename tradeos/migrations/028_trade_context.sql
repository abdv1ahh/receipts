-- Migration 028: what the world was showing when a trade was logged (Phase 6, the Journal).
--
-- A journal records what the trader did. It cannot see what was happening at the time, so it can
-- only ever coach on outcomes — and coaching on outcomes teaches a trader to feel good about lucky
-- wins. This table is the other half: the Radar as it stood at the moment of entry, frozen.
--
-- It is written ONCE, at trade creation, and never updated when the trade is edited. That is the
-- whole point. If a later edit could move the context, the record would drift toward whatever the
-- trader now believes was happening, which is precisely the bias the journal exists to counter.
--
-- `basis` is load-bearing honesty. 'live' means captured at the moment of entry. 'reconstructed'
-- means derived afterwards from claims whose created_at proves they were live then — a real fact
-- from the record, but ranked against the reader's CURRENT frame rather than the one they had at
-- the time. The two are never pooled silently; the interface says which it is showing.

CREATE TABLE trade_context (
    trade_id     bigint PRIMARY KEY REFERENCES trades(id) ON DELETE CASCADE,
    captured_at  timestamptz NOT NULL DEFAULT now(),   -- when the snapshot was taken
    as_of        timestamptz NOT NULL,                 -- the moment it describes (trade creation)
    basis        text NOT NULL DEFAULT 'live'
                 CHECK (basis IN ('live', 'reconstructed')),

    claim_ids    bigint[] NOT NULL DEFAULT '{}',       -- the claims that were live, most relevant first
    n_live       int NOT NULL DEFAULT 0,               -- how many were live in total, not just stored
    n_on_symbol  int NOT NULL DEFAULT 0,               -- how many named this trade's symbol

    -- Did a live interpretation on this name point the same way as the trade? with | against |
    -- mixed | none. This is the process fact the coach reasons over; the outcome is separate.
    alignment    text CHECK (alignment IN ('with', 'against', 'mixed', 'none')),

    -- Mean novelty of the live claims: was this a day the news was breaking, or a quiet one?
    mean_novelty real,

    -- The frozen payload: the claims themselves as they read at the time, so the trade detail can
    -- show them even after the claim is resolved, re-scored, or its cluster re-derived.
    snapshot     jsonb NOT NULL DEFAULT '{}'
);

CREATE INDEX trade_context_alignment_idx ON trade_context (alignment);

INSERT INTO schema_migrations (version) VALUES (28);
