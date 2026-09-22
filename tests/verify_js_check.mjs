// The JavaScript half of the cross-language guard on the sealed wire format. Run by `make test-js`.
//
// WHY THIS IS NOT A PYTEST. `chain.py` and `receipts/verify.js` must produce byte-identical
// payloads forever — a JS framing that disagrees by one byte would tell every visitor that an
// intact record is broken, on the one interaction the product is sold on. The obvious place to
// assert that is the Python suite, and the Python suite cannot run it: `make test` runs inside the
// API image, which carries no node (the frontend is built in a separate Docker stage), and the
// host that has node has no Python dependencies. A test that can run in neither place is not a
// guard, it is a comment.
//
// So both sides check the same committed fixture instead:
//
//   tests/fixtures/receipt_chain.json   five links sealed by `chain.seal`, including an empty
//                                       thesis, a 4-byte emoji, and a thesis that spells out a
//                                       field header to try to smuggle structure past the framing
//   tests/test_receipts_chain.py        asserts Python still reproduces every hash in it
//   this file                           asserts JavaScript does too, and catches every tamper
//
// Pinning both to one fixture pins them to each other. Change the wire format and both fail.
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { framePayload, verifyChain } from "../tradeos/receipts/verify.js";

const here = dirname(fileURLToPath(import.meta.url));
const fixture = () => JSON.parse(readFileSync(join(here, "fixtures", "receipt_chain.json"), "utf8"));

let failures = 0;

function check(name, condition, detail) {
  if (condition) {
    console.log(`  ok    ${name}`);
  } else {
    failures += 1;
    console.log(`  FAIL  ${name}${detail ? `\n        ${detail}` : ""}`);
  }
}

console.log("verify.js against the sealed fixture");

// 1. The chain Python sealed verifies in JavaScript.
const intact = await verifyChain(fixture());
check("the fixture chain recomputes", intact.intact === true, intact.reason);
check("every link was checked", intact.checked === fixture().links.length);
check("the head matches the last stored hash",
      intact.head === fixture().links.at(-1).content_hash);

// 2. The length prefix counts BYTES. The emoji in link 3 is one character and four bytes, so a
//    verifier using `.length` reports a healthy record as broken.
const third = fixture().links[2];
const framed = framePayload(fixture().fields, third.values);
const byteLen = new TextEncoder().encode(third.values.thesis).length;
check("the thesis is prefixed with its byte length, not its character count",
      framed.includes(`thesis:${byteLen}:`) && byteLen > third.values.thesis.length,
      `bytes ${byteLen}, characters ${third.values.thesis.length}`);

// 3. Every way of altering history is caught, and named at the right link.
const edited = fixture();
edited.links[2].values.thesis += " ";                     // one trailing space
const e = await verifyChain(edited);
check("a one-character edit is caught at that call",
      e.intact === false && e.broken_at_seq === 3, JSON.stringify(e));

const removed = fixture();
removed.links.splice(1, 1);
const r = await verifyChain(removed);
check("a deleted call is caught as a gap",
      r.intact === false && r.broken_at_seq === 3, JSON.stringify(r));

// Swapping the two links' POSITION in the array is not a tamper and must not be reported as one:
// both implementations sort by seq first, because the order they arrive in is transport, not
// evidence. Reordering history means changing the sequence numbers themselves, which is this.
const reordered = fixture();
[reordered.links[1].seq, reordered.links[2].seq] = [reordered.links[2].seq, reordered.links[1].seq];
reordered.links[1].values.seq = String(reordered.links[1].seq);
reordered.links[2].values.seq = String(reordered.links[2].seq);
const s = await verifyChain(reordered);
check("two calls given each other's place in the sequence are caught",
      s.intact === false && s.broken_at_seq === 2, JSON.stringify(s));

const transportOrder = fixture();
transportOrder.links.reverse();
const t = await verifyChain(transportOrder);
check("the same chain sent newest-first still verifies", t.intact === true, JSON.stringify(t));

const repointed = fixture();
repointed.links[3].prev_hash = repointed.links[1].content_hash;
const p = await verifyChain(repointed);
check("a re-pointed link is caught at that call",
      p.intact === false && p.broken_at_seq === 4, JSON.stringify(p));

const backdated = fixture();
backdated.links[0].values.published_at = "2026-01-01T00:00:00.000000Z";
const b = await verifyChain(backdated);
check("a backdated call is caught at the first link",
      b.intact === false && b.broken_at_seq === 1, JSON.stringify(b));

// 4. An empty record is intact and says so, rather than throwing.
const none = await verifyChain({ ...fixture(), links: [] });
check("an empty record is intact", none.intact === true && none.checked === 0);

console.log(failures ? `\n${failures} failed` : "\nall passed");
process.exit(failures ? 1 : 0);
