// Check every exported record, offline, with no server and no dependencies.
//
//     node check.mjs
//
// It reads each <handle>.json beside it and recomputes every SHA-256 with `verify.js` — the SAME
// file this product serves to a browser, copied here verbatim, not a second implementation. A
// frozen wire format with two implementations already needs a cross-language test to keep them
// honest; a third would be a liability, not a reassurance.
//
// Exit status is 0 only if every record verifies.
import { readFileSync, readdirSync } from "node:fs";
import { createHash } from "node:crypto";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

// verify.js reaches for WebCrypto, which node exposes on `globalThis.crypto` from 19 and behind a
// flag before that. Providing the one primitive it uses keeps the browser file unmodified, which
// is the whole point of copying rather than porting it.
if (!globalThis.crypto?.subtle) {
  globalThis.crypto = {
    subtle: {
      digest: async (_alg, data) =>
        createHash("sha256").update(Buffer.from(data)).digest().buffer,
    },
  };
}

const here = dirname(fileURLToPath(import.meta.url));
const { verifyChain } = await import(join(here, "verify.js"));

const manifest = JSON.parse(readFileSync(join(here, "MANIFEST.json"), "utf8"));
const records = readdirSync(here).filter(
  (f) => f.endsWith(".json") && f !== "MANIFEST.json");

let failed = 0;
for (const file of records.sort()) {
  const body = JSON.parse(readFileSync(join(here, file), "utf8"));
  const started = Date.now();
  const out = await verifyChain(body);
  const ms = Date.now() - started;
  const sealed = manifest.files?.[file]?.sealed_after_the_outcome_was_known;
  const note = sealed ? "  [SEALED BACKTEST - see README]" : "";
  if (out.intact) {
    console.log(`ok    ${body.handle}: ${out.links} links in ${ms} ms, head ${out.head.slice(0, 16)}${note}`);
  } else {
    failed += 1;
    console.log(`BROKEN ${body.handle}: ${out.reason} at call #${out.broken_at_seq}`);
  }
}

// Tamper with one byte and confirm the check says no. A checker that can only ever print "ok" is
// indistinguishable from a checker that does nothing, and a reader has no way to tell them apart
// unless they watch it fail.
if (records.length) {
  const body = JSON.parse(readFileSync(join(here, records[0]), "utf8"));
  const field = body.fields[body.fields.length - 1];
  body.links[0].values[field] = body.links[0].values[field] + "x";
  const out = await verifyChain(body);
  if (out.intact) {
    console.log("BROKEN the checker did not notice a tampered record; it is not checking anything");
    failed += 1;
  } else {
    console.log(`ok    and it says no when it should: ${out.reason} at call #${out.broken_at_seq}`);
  }
}

console.log(failed ? `\n${failed} problem(s)` : `\nall ${records.length} record(s) verified`);
process.exit(failed ? 1 : 0);
