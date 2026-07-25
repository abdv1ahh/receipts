-- Migration 027: give a claim a place to record where it came from.
--
-- Signal-plane claims need a stable key so re-importing cannot duplicate them. The first cut
-- appended "[convergence:43684:30]" to the mechanism text and matched on that — which worked, and
-- put an internal identifier in front of every reader on the Ledger. Provenance belongs in a
-- column, not in prose the user has to read past.

ALTER TABLE claims ADD COLUMN source_ref text;
CREATE UNIQUE INDEX claims_source_ref_idx ON claims (source_ref) WHERE source_ref IS NOT NULL;

-- Move the markers already written into prose out to the new column, then strip them.
UPDATE claims
   SET source_ref = substring(mechanism from '\[(convergence:[0-9]+:[0-9]+)\]'),
       mechanism  = btrim(regexp_replace(mechanism, '\s*\[convergence:[0-9]+:[0-9]+\]\s*', '', 'g'))
 WHERE mechanism LIKE '%[convergence:%';

INSERT INTO schema_migrations (version) VALUES (27);
