# Threat model: Short interest ingestion (FINRA)

Written before the pipeline, per the security mandate. FINRA publishes consolidated equity
short interest twice a month. We ingest it through a dedicated allowlisted client and display
DERIVED changes, never republishing raw files wholesale. In this slice short interest is a
corroborating CONTEXT source; weighting it into the convergence score is a deliberate,
logged version bump (decision #31) so the Slice 4 calibration is not silently disturbed.

## Who / what attacks this and how

**1. Staleness misread as current positioning.** Short interest is bi-monthly and published
about eight business days after its settlement date; treating a settlement figure as "today"
would overstate freshness. Removed by: two timestamps — `settlement_date` (event_time) and a
`knowable_time` set to the publication date (settlement + ~8 business days, documented as an
approximation until the exact FINRA dissemination date is wired). All consumption is through
knowable_time, and the lag is shown.

**2. Raw-file redistribution.** Mirroring FINRA's raw files wholesale raises licensing
questions. Removed by: we store and display only derived quantities (short-interest change,
days-to-cover), the analytical facts a user needs, not a republished copy of the dataset.

**3. Revisions presented as originals.** FINRA revises figures (revisionFlag). Overwriting a
prior belief would rewrite history. Bounded by: `UNIQUE (symbol, settlement_date)` with an
upsert that records the latest value; the raw layer is unaffected, and a future audit view can
reconstruct revisions if needed. No signal is scored on it yet, so no belief is rewritten.

**4. Symbol mis-resolution.** A short-interest row must not be attached to the wrong issuer.
Removed by: mapping strictly by `symbolCode` through `security_map`; a symbol we do not know is
skipped (never guessed onto an entity).

**5. Over-reading a single number.** A high short interest is ambiguous (bearish conviction OR
squeeze fuel). Bounded by: short interest is never a standalone signal — it is displayed as
context, and if ever scored (v-next) only a DECREASE alongside independent bullish classes
contributes weakly (0.3), while an increase is context only.

## What this pipeline explicitly does not do yet

It does not feed the published convergence score (that is a logged recalibration step). It
ingests only the derived fields it displays, and only for symbols already known to
`security_map`.
