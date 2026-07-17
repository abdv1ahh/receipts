# Threat model: Schedule 13D / 13G ingestion pipeline

Written before the pipeline, per the security mandate. Each attack names the design
property that removes it, not a mitigation that merely discourages it. This pipeline
inherits every control in the Form 4 threat model (same `EdgarClient`: HTTPS-only,
host allowlist, throttle, checksum, no-redirects); only the additions are listed here.

## Who attacks this and how

**1. Parse error presented as fact.** 13D/13G are the messiest EDGAR forms: the cover
pages are free-form HTML tables, and the fields a naive scraper wants — percent of
class, date of event — do not survive tag-stripping and are ambiguous when multiple
reporting persons appear. A scraper that guesses a percentage from the first `NN.NN%`
token in the body will publish a fabricated number. Removed by: **we parse only the
SGML submission header**, which is machine-structured and authoritative (subject-company
CIK/name, filer CIK/name, form type, acceptance datetime, SEC file number, and
`CONFORMED PERIOD OF REPORT` when present). `percent_owned` is stored NULL rather than
guessed from HTML; `event_time` uses the header period when present and otherwise falls
back to the filing date with `parse_confidence = 'filing_date_fallback'` recorded on the
row. Nothing derived from the HTML body is ever presented as a measured fact. This is
honesty rule 1 made structural.

**2. Feed-type spoofing via label drift.** The daily index labels these
`SCHEDULE 13D` / `SCHEDULE 13G` / `SCHEDULE 13D/A` / `SCHEDULE 13G/A` (not the `SC 13D`
shorthand used elsewhere at the SEC). A filter keyed to the wrong label silently ingests
nothing — a feed that is broken but looks healthy. Removed by: the form-type allowlist
matches the exact index labels, and `feed_health` plus `ingest_rejects` surface a day
that produced zero rows, so an empty feed degrades loudly rather than passing as "no
activity."

**3. Fraudulent or coordinated activist filings.** An adversary files a false 13D to
manufacture an "activist stake" signal on a thinly traded name. Same residual risk as
Form 4 (we cannot police the SEC's intake). Mitigated (not removed) by: the CIK of the
named filer is recorded, and at the signal layer (Slice 3) by the liquidity floor,
multi-source corroboration, and independence collapse so a single filer cannot by itself
clear the publish gate.

**4. Amendment overwrite / belief rewriting.** A 13D/A must never overwrite the original
stake it amends (honesty rule 5). EDGAR headers do not carry the parent accession, but
every filing in an amendment series shares one `SEC FILE NUMBER` (005-xxxxx). Removed by:
amendments insert as new rows carrying `file_number`; current-state views reconstruct
belief by ordering a series on `knowable_time`. No row is ever mutated (raw layer trigger
still forbids UPDATE/DELETE).

**5. Unresolved issuer shown as resolved.** A subject company whose CIK we cannot map to
a tradable security must not be silently attached to the wrong entity. Removed by: the
never-guess rule — an unresolvable issuer is stored with `issuer_entity` NULL, excluded
from convergence, and displayed flagged "unresolved" in browse views.

## What this pipeline explicitly does not do yet

It does not parse the HTML cover page at all (percent-owned, item-by-item ownership
detail). That is a deliberate deferral, not an omission: the header gives us who filed
on whom and when, which is the convergence-relevant fact. Cover-page structured
extraction, if ever justified, is a separate work item with its own validation, and until
then the absence is honest — `percent_owned` reads NULL, not a guess.
