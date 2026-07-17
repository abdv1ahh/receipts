# Threat model: Form 13F-HR ingestion pipeline

Written before the pipeline, per the security mandate. Inherits every `EdgarClient`
control from the Form 4 threat model (HTTPS-only, host allowlist, throttle, checksum,
no-redirects, defusedxml). Only the additions are listed here.

## Who attacks this and how

**1. Staleness misread as freshness.** This is the defining risk of 13F. A quarterly
snapshot can be up to 45 days stale at filing and months stale by the time a user reads
it; presenting a 13F position as if it were current would be the platform's first
dishonest number. Removed by: the two-timestamp schema is not optional here —
`event_time` = `CONFORMED PERIOD OF REPORT` (quarter end) and `knowable_time` =
`ACCEPTANCE-DATETIME` are stored as separate columns with no app-side derivation, so the
gap is queryable and rendered as a first-class freshness signal in every surface (Slice 3
`<Freshness>` component). The signal layer additionally weights 13F lowest of all classes
and decays it on a 60-day half-life precisely because it is stale.

**2. XXE / entity-expansion via the information table.** A 13F carries a large XML
`informationTable`; a malicious or malformed one could carry external entities or an
expansion bomb. Removed by: defusedxml (DTDs and entity expansion rejected outright), the
same control proven for Form 4. Namespaced elements are matched with the `{*}` wildcard so
the parser cannot be evaded by namespace tricks.

**3. Silent row loss via a too-strict uniqueness key.** Real information tables list the
same security multiple times in one filing (different investment discretion / other
managers). A `UNIQUE (accession_no, cusip, share_type)` with `ON CONFLICT DO NOTHING` over
raw rows would drop the duplicates and silently understate a position. Removed by:
holdings are **aggregated within a filing** — shares and value summed per
(cusip, share_type) — so one honest total position is stored per security per filing and
the uniqueness key holds without dropping data (decision log #18).

**4. Value-unit corruption.** 13F reported `value` in thousands of dollars before the
SEC's 2023 amendment and in whole dollars after; mixing the two silently corrupts every
magnitude. Removed by: normalization to whole USD keyed on `period_end`, recorded in code
and on the methodology page. The demo backfill window (8 recent quarters) is entirely in
the post-2023 whole-dollar regime, so normalization is a documented safety net rather than
an active transform for demo data (decision log #17).

**5. Corrupt or truncated upstream table.** A damaged info table or a pre-2013 filing with
no structured table. Removed as a silent-failure class by: per-filing error isolation and
loud rejects into `ingest_rejects` (a filing with no parseable `informationTable` is
logged and skipped, not half-ingested), plus `feed_health` counters surfaced in the
product. Pre-2013 filings are explicitly out of scope and logged as skipped.

**6. Replay / duplication corrupting counts.** Re-running a day or a quarter must be a
no-op. Removed by: `raw_filings.accession_no` uniqueness on the raw layer and
`UNIQUE (accession_no, cusip, share_type)` on `fund_holdings`, both database constraints,
plus the append-only trigger forbidding UPDATE/DELETE.

## What this pipeline explicitly does not do yet

It ingests the modern structured `informationTable` only; pre-2013 unstructured 13F is out
of scope for the demo and skipped loudly. CUSIP → issuer resolution is best-effort via the
resolution module (OpenFIGI); an unresolved CUSIP stays unresolved and its holding is
excluded from convergence but visible in browse, never guessed onto a wrong issuer.
