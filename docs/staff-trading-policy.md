# Staff trading policy (template for signature at incorporation)

Employees and the founder see aggregated signals before the public does. Regulators will
eventually ask how that access was controlled, and the honest answer needs to exist from the
start (founding brief). This is a one-page template to adopt and sign when the entity is formed;
the platform already logs the access it describes.

## Policy

1. **No trading on pre-publication signals.** No member of staff (including founders) may trade
   any security based on a TradeOS signal before that signal is public to the free tier. The
   free tier sees signals on a 48-hour delay; staff are bound by at least that delay, and by a
   blackout until a specific cluster is public to the free tier.

2. **No trading ahead of a signal you helped compute or curate.** If you touched the data,
   model, or curation for a name, you do not trade that name around the signal window.

3. **All staff access to pre-publication signal data is logged.** Admin/staff reads of clusters
   newer than the free-tier delay window are written to the append-only `audit_log` with action
   `prepub_access` (already implemented). The log is immutable (trigger-enforced) and is the
   record produced on request.

4. **Personal-account disclosure.** Staff disclose brokerage accounts and, where required,
   pre-clear trades in names the platform covers.

5. **Enforcement.** Violations are grounds for termination and, where applicable, reporting.

## Why this exists now
The platform being used as a pump instrument — or staff front-running its own users — is a
business-ending event, so it gets business-ending seriousness. The technical control
(prepub_access logging) is live before the policy is signed, so the paper trail starts on day
one rather than being reconstructed later.
