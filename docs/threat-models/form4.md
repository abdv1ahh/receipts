# Threat model: Form 4 ingestion pipeline

Written before the pipeline, per the security mandate. Each attack names the design
property that removes it, not a mitigation that merely discourages it.

## Who attacks this and how

**1. Feed spoofing / man in the middle.** An attacker redirects our fetches to a
server serving fabricated filings, injecting fake insider buys to pump an asset.
Removed by: HTTPS only, host allowlist hardcoded to sec.gov domains in
`edgar_client.py`, redirects not followed, and a deployment-level egress allowlist
so the ingestion container cannot reach any other host even if code is compromised.

**2. SSRF via ingestion.** The system fetches URLs, so an attacker who influences a
URL (e.g. through a poisoned index file) steers a fetch at cloud metadata or internal
services. Removed by: URLs are constructed by us from date arithmetic and index
filenames, the filename is validated to yield an accession number, the client rejects
any host outside the allowlist before connecting, and the container network cannot
reach metadata endpoints.

**3. XXE / parser exploitation.** A malicious XML document with external entities or
entity-expansion bombs. Removed by: defusedxml, which rejects DTDs and entity
expansion outright. Tested in `test_parse_rejects_external_entities`.

**4. Fraudulent filings.** An adversary files false Form 4s with the SEC to
manufacture a signal. Rare because it is felony securities fraud with a named filer,
but not impossible. Mitigated (not removed; we cannot verify the SEC's own intake)
by: range sanity checks, and at the signal layer (Slice 3) by liquidity floors,
multi-source corroboration requirements, and first-time-asset review before alerts.

**5. Corrupt or malformed upstream data.** Truncated files, encoding damage, schema
drift after an SEC format change. Removed as a silent failure class by: schema
validation with loud rejects into `ingest_rejects`, per-filing error isolation so one
bad document never kills a day, and `feed_health` counters surfaced in the product
itself. A feed that degrades does so visibly.

**6. Us as the attacker (fair access abuse).** Hammering EDGAR gets the platform
blocked, which is an availability incident. Removed by: hard client-side throttle at
~4 req/s (SEC ceiling is 10), exponential backoff on 429/5xx, and a mandatory
declared User-Agent with contact address, enforced in code.

**7. Replay / duplication corrupting counts.** Re-running a day must not double
signals. Removed by: accession number uniqueness on the raw layer and
(accession, seq, owner) uniqueness on the derived layer, both database constraints,
plus the append-only trigger forbidding UPDATE/DELETE on raw_filings.

## What this pipeline explicitly does not defend yet

Amendment reconciliation (4/A linking to the accession it amends) is stored but not
yet reconciled into signal views; that lands with the signals module. Until then no
signal is computed, so no user-facing consequence exists.
