-- TradeOS migration 017: admin dashboard (Slice K).
-- Two additive changes that give the admin console real teeth:
--   1) users.banned — a suspend switch. A banned account gets no valid session (authn) and its
--      public trades are hidden on ban; enforcement is server-side, never a client flag.
--   2) content_reports resolution columns — resolving a report is NON-destructive: we stamp who
--      resolved it, when, and how (hide/unhide/dismiss), instead of deleting the report. This keeps
--      an honest moderation trail AND lets the auto-hide counter (community.report) reset after a
--      dismissal, since it now counts only unresolved reports.
-- Feature flags reuse the existing feature_flags table (migration 009) — no new table needed; the
-- admin flag console flips rows there and tradeos/flags.py reads them on the request path.

ALTER TABLE users ADD COLUMN banned boolean NOT NULL DEFAULT false;

ALTER TABLE content_reports ADD COLUMN resolved_at timestamptz;
ALTER TABLE content_reports ADD COLUMN resolved_by text;         -- admin email (from the audit actor)
ALTER TABLE content_reports ADD COLUMN resolution  text;         -- 'hide' | 'unhide' | 'dismiss'

-- The moderation queue and the auto-hide counter both look only at OPEN reports.
CREATE INDEX idx_reports_open ON content_reports (target_type, target_id) WHERE resolved_at IS NULL;

INSERT INTO schema_migrations (version) VALUES (17);
