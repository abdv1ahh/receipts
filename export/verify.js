// The visitor's own check, run in the visitor's own browser.
//
// WHY THIS IS NOT A CALL TO `/api/receipts/{handle}/verify`. That endpoint recomputes the chain on
// our server and answers "intact: true", which is the operator of the database asking to be
// trusted — on the one page whose entire argument is that you do not have to trust us. So the
// server hands over the sealed fields and states no verdict, and this file does the hashing on the
// machine of the person who is sceptical. It is shipped as a FILE rather than inlined because the
// app sends `script-src 'self'`: an inline script is refused by the browser with nothing in our
// logs, which would leave the flagship interaction of the product dead on the page.
//
// WHAT IT PROVES, precisely, because overclaiming here would be worse than having no button:
//   * the text on this page hashes to the published chain, and every link joins to the one before
//     it, so the CALLER cannot have edited, deleted, reordered or backdated anything;
//   * it does NOT prove we have not rewritten the whole chain from some point. We hold every
//     field. Closing that needs an anchor outside our control and it is not built. The panel says
//     so in those words, unprompted, at the moment the visitor is most impressed.
//
// THE FRAMING BELOW IS A FROZEN WIRE FORMAT. `name:byte-length:value`, joined with newlines,
// hashed as (prev_hash + payload). The length is in BYTES, not characters — an emoji in a thesis
// is one character and four bytes, and getting that wrong would report every record containing one
// as broken. The server renders each value to text (`chain.rendered_fields`) so this file never
// has to reinvent how a timestamp is spelled; a `Date` round trip drops the microseconds and the
// trailing Z, both of which are part of the sealed bytes.
//
// THE GUARD AGAINST THE TWO DRIFTING IS `make test-js`, and it is not `make test`. The Python
// suite cannot run this file: it runs inside the API image, which carries no node, and CI's
// pytest job has no database, so every test that would reach it skips. Both languages check one
// committed fixture instead — `tests/fixtures/receipt_chain.json`, pinned from Python by
// `test_receipts_chain.py` and from here by `tests/verify_js_check.mjs`, which CI's `web` job
// runs because node is already set up there. Run `make test-js` after touching either side.

const encoder = new TextEncoder();

// How many computed links the walk keeps for display. The hashing is over before anything is
// drawn, so this bounds only the memory the ANIMATION holds — a 10,000-call record would otherwise
// retain every intermediate hash to draw forty frames. The counter never reads this; see `replay`.
const SAMPLE_CAP = 400;

/** sha256 of a string, hex. WebCrypto, which is the same primitive `hashlib` uses. */
export async function sha256Hex(text) {
  const digest = await crypto.subtle.digest("SHA-256", encoder.encode(text));
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

/** The canonical payload for one link: each sealed field as `name:bytes:value`, newline joined. */
export function framePayload(fields, values) {
  return fields
    .map((name) => {
      const value = values[name];
      return `${name}:${encoder.encode(value).length}:${value}`;
    })
    .join("\n");
}

/**
 * Walk the whole chain, recomputing every hash.
 *
 * Mirrors `chain.verify_chain` exactly, including which failure is reported: the FIRST link that
 * does not reconcile. Once a link breaks, every later link was computed over a wrong prev_hash and
 * would be reported broken too, burying the actual edit under its own consequences.
 *
 * `onLink` is called with each link's result as it is computed, so the caller can show the work.
 */
export async function verifyChain(body, onLink) {
  const links = [...body.links].sort((a, b) => a.seq - b.seq);
  const fields = body.fields;
  let prev = body.genesis;
  const started = now();

  for (let i = 0; i < links.length; i += 1) {
    const link = links[i];
    const expectedSeq = i + 1;

    // A gap or a duplicate is a break in its own right: without this, removing a call and
    // renumbering nothing would leave every remaining hash self-consistent, and a deletion is
    // precisely what this exists to catch.
    if (link.seq !== expectedSeq) {
      return broken(links, i, link.seq, String(expectedSeq), String(link.seq),
                    "the sequence has a gap or a duplicate, so a call is missing", started);
    }
    if (link.prev_hash !== prev) {
      return broken(links, i, link.seq, prev, link.prev_hash,
                    "this call does not chain from the one before it", started);
    }

    const payload = framePayload(fields, link.values);
    const recomputed = await sha256Hex(prev + payload);
    if (recomputed !== link.content_hash) {
      return broken(links, i, link.seq, recomputed, link.content_hash,
                    "the stored hash does not match the call's own contents", started);
    }
    prev = recomputed;
    if (onLink) onLink({ index: i + 1, link, recomputed, payload });
  }

  return {
    intact: true, links: links.length, checked: links.length, broken_at_seq: null,
    expected: null, found: null, head: links.length ? prev : body.genesis,
    reason: "every link recomputes from the published fields",
    ms: Math.round(now() - started),
  };
}

function broken(links, index, seq, expected, found, reason, started) {
  return { intact: false, links: links.length, checked: index, broken_at_seq: seq,
           expected, found, reason, head: null, ms: Math.round(now() - started) };
}

function now() {
  return typeof performance !== "undefined" ? performance.now() : Date.now();
}

// ------------------------------------------------------------------ the panel
//
// Everything below runs only in a browser. The `typeof document` guard is what lets the three
// exports above be imported under node by `tests/verify_js_check.mjs`, which is the guard on the
// wire format — see the header. Remove it and that check cannot load this file at all.

if (typeof document !== "undefined") {
  document.addEventListener("DOMContentLoaded", wire);
}

function wire() {
  const panel = document.querySelector("[data-verify]");
  if (!panel) return;
  const go = panel.querySelector("[data-verify-go]");
  const live = panel.querySelector("[data-verify-live]");
  const bar = panel.querySelector("[data-verify-bar]");
  const row = panel.querySelector("[data-verify-row]");
  const count = panel.querySelector("[data-verify-count]");
  const result = panel.querySelector("[data-verify-result]");
  // The first-screen control. It is queried from the document, not the panel, because it sits in
  // the hero above the fold — and it is bound to the SAME `run()` below, so there is one code
  // path with two views rather than a second verifier that can disagree with the first.
  const miniGo = document.querySelector("[data-verify-mini-go]");
  const miniOut = document.querySelector("[data-verify-mini-out]");

  // The button is hidden in the stylesheet and revealed here. Without JavaScript it would be a
  // control that visibly does nothing, which on this page is worse than one that is not offered.
  panel.classList.add("ready");
  // Reveal by CLASS, so the box was always in the layout and nothing below it moves.
  if (miniGo) miniGo.closest("[data-verify-mini]").classList.add("ready");

  // WebCrypto exists only in a SECURE CONTEXT — https, or localhost. Over plain http on a LAN
  // address, which is exactly what a bare `docker compose up` with no proxy in front serves,
  // `crypto.subtle` is undefined and every hash throws. Checked up front so the panel says which
  // of the two possible things is wrong, rather than the button dying mid-walk.
  if (!globalThis.crypto?.subtle) {
    go.disabled = true;
    if (miniGo) { miniGo.disabled = true; say(miniOut, "needs https to check here"); }
    failure(result, "This page has to be served over HTTPS to check it here.",
            "The arithmetic runs on your device, and browsers only expose the hashing they need "
            + "for it on a secure connection. Nothing is wrong with the record — open this page "
            + "over https and the check will run.");
    return;
  }

  let chain = null;          // the downloaded links, kept so "check again" costs one fetch
  let busy = false;

  const run = async (tamper) => {
    if (busy) return;
    busy = true;
    result.hidden = true;
    result.replaceChildren();
    live.hidden = false;
    go.disabled = true;
    if (miniGo) miniGo.disabled = true;
    if (miniOut) { miniOut.className = "pr-mini-out"; say(miniOut, "downloading every sealed call…"); }
    say(count, tamper ? "Fetching the same calls again…" : "Downloading every sealed call…");
    setBar(bar, 0);

    // The WHOLE run is guarded, not just the fetch. This covered only the download at first, so
    // anything thrown by the hashing, the replay or the render rejected a promise nobody was
    // awaiting and left `busy` true, the button disabled and the progress bar frozen at zero,
    // with no message — a dead flagship interaction and nothing on screen to say so.
    try {
      if (!chain) {
        const res = await fetch(`/api/receipts/${encodeURIComponent(panel.dataset.handle)}/chain`,
                                { headers: { accept: "application/json" } });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        chain = await res.json();
      }

      const body = tamper ? withOneCharacterChanged(chain) : chain;
      const n = body.links.length;
      say(count, n === 1
        ? "The call is now in your browser. Recomputing its fingerprint here."
        : `${n} calls are now in your browser. Recomputing every fingerprint here.`);

      // The hashing itself takes a few dozen milliseconds for a record of this size, which is too
      // fast to see. So the real work is done first and the walk is REPLAYED at a readable pace,
      // and the panel says that in those words rather than pretending the delay is the work. An
      // honest replay is more convincing than a fake progress bar, because the numbers it shows
      // are the ones that were actually computed.
      //
      // At most SAMPLE_CAP steps are kept, because a 10,000-call record would otherwise hold every
      // intermediate hash in memory to animate forty frames. `replay` samples across whatever it
      // is given and drives the bar from the TOTAL, so a capped sample still finishes at 100%.
      const steps = [];
      const out = await verifyChain(body, (step) => {
        if (steps.length < SAMPLE_CAP) steps.push(step);
      });
      await replay(steps, out, { bar, row, count, total: n, mini: miniOut });
      render(result, out, body, tamper, run);
      if (miniOut) {
        miniOut.className = `pr-mini-out ${out.intact ? "ok" : "broken"}`;
        const one = out.checked === 1;
        say(miniOut, out.intact
          ? (one ? `recomputed on this device in ${howLong(out.ms)}, and it matched`
                 : `all ${out.checked} recomputed on this device in ${howLong(out.ms)}, `
                   + "every one matched")
            + " — see how, and what it does not prove, below"
          : `broken at call #${out.broken_at_seq} — the full check is below`);
      }
    } catch (err) {
      failure(result, "The check could not be run.",
              "That is a problem at our end or on the way here, not a finding about this record. "
              + `(${err.message})`);
    } finally {
      live.hidden = true;
      go.disabled = false;
      if (miniGo) miniGo.disabled = false;
      busy = false;
    }
  };

  go.addEventListener("click", () => run(false));
  if (miniGo) {
    // Answers in place, and does NOT scroll. Jumping a reader 1,300px the instant they press a
    // button loses their place on the one screen that was just built to hold them. The full panel
    // is running the same job at the same time, so what they get here is the real answer; the
    // mini result then POINTS at the walk and the caveat instead of dragging them to it.
    miniGo.addEventListener("click", () => run(false));
  }
}

/** One character of one thesis, changed in the browser and nowhere else.
 *
 *  This is the most useful thing on the panel. A check that can only ever say yes is a green
 *  sticker, and a visitor has no way to tell one from the other — so the page offers to break the
 *  record in front of them, with the same code, and show it being caught. Nothing is sent
 *  anywhere; the stored record is untouched. */
function withOneCharacterChanged(body) {
  const links = body.links.map((l) => ({ ...l, values: { ...l.values } }));
  const target = links[Math.floor(links.length / 2)] || links[0];
  const field = target.values.thesis ? "thesis" : "symbol";
  const original = String(target.values[field]);
  target.values[field] = original.slice(0, -1) + (original.slice(-1) === "x" ? "y" : "x");
  return { ...body, links, tamperedSeq: target.seq, tamperedField: field };
}

/**
 * Walk the result in front of the reader, at a pace they can follow.
 *
 * The COUNTER is driven by the run's own totals, never by how many steps were sampled. Reading it
 * off the sample made the walk stop at "400 of 1000 fingerprints recomputed" one beat before the
 * result panel said "all 1000 recomputed and every one matched" — two sentences contradicting each
 * other, on the one panel whose entire argument is that it does not overstate. The sample only
 * decides which links are NAMED as they go past.
 */
async function replay(steps, out, ui) {
  const reached = out.intact ? ui.total : Math.max(1, out.checked);
  const shown = out.intact ? steps : steps.slice(0, reached);
  const budget = 850;                                     // milliseconds, the whole walk
  const frames = Math.min(Math.max(shown.length, 1), 40);
  if (!ui.total) { setBar(ui.bar, 1); return; }
  for (let f = 1; f <= frames; f += 1) {
    const progress = f / frames;
    const done = Math.max(1, Math.round(progress * reached));
    const step = shown[Math.max(0, Math.round(progress * shown.length) - 1)];
    setBar(ui.bar, done / ui.total);
    if (step) {
      const v = step.link.values;
      say(ui.row, `#${v.seq}  ${v.symbol}  ${String(v.published_at).slice(0, 10)}  `
                  + `→ ${step.recomputed.slice(0, 12)}…  matches`);
    }
    say(ui.count, `${done} of ${ui.total} fingerprints recomputed in your browser`);
    if (ui.mini) say(ui.mini, `${done} of ${ui.total} recomputed here…`);
    await sleep(budget / frames);
  }
}

function render(target, out, body, wasTampered, run) {
  target.hidden = false;
  target.replaceChildren();
  target.className = `pr-result ${out.intact ? "ok" : "broken"}`;

  if (out.intact) {
    if (wasTampered) {
      // Defensive: reaching here would mean the demonstration failed to break anything, and
      // claiming a tamper was caught when it was not is the one lie this panel must not tell.
      failure(target, "The demonstration did not change anything.",
              "Nothing was altered, so there was nothing to catch. The record itself is untouched.");
      return;
    }
    const one = out.checked === 1;
    add(target, "b", one
      ? "Intact. Your browser recomputed the fingerprint and it matched."
      : `Intact. Your browser recomputed all ${out.checked} fingerprints and every one matched.`);
    add(target, "p", (one ? "The call was" : `All ${out.checked} calls were`)
                     + ` downloaded to this device and hashed here with SHA-256, in ${howLong(out.ms)}`
                     + ". Nothing was checked on our server — we only handed over the sealed text.");
  } else if (wasTampered) {
    add(target, "b", `Caught, at call #${out.broken_at_seq}.`);
    add(target, "p", `One character of one ${body.tamperedField} was changed in your browser just `
                     + `now. The check reached call ${out.checked + 1} and stopped: ${out.reason}. `
                     + "Nothing was sent anywhere and the published record is untouched — reload "
                     + "the page and it verifies again.");
  } else {
    add(target, "b", `Broken at call #${out.broken_at_seq}.`);
    add(target, "p", `${out.reason}. Expected ${short(out.expected)}, found ${short(out.found)}.`);
  }

  const actions = add(target, "div", "");
  actions.className = "pr-result-actions";
  if (!wasTampered && out.intact) {
    const demo = add(actions, "button", "Now show me it failing");
    demo.className = "pr-linkbtn";
    demo.addEventListener("click", () => run(true));
  }
  const again = add(actions, "button", wasTampered ? "Check the real record again" : "Check again");
  again.className = "pr-linkbtn";
  again.addEventListener("click", () => run(false));

  if (out.intact && !wasTampered) showOneLink(target, body);

  // The caveat, unprompted, at the moment the visitor is most impressed. It is the strongest
  // argument the page makes that it is not selling them anything. The words come from
  // `record.methodology`, which is where every other surface reads them from.
  const caveat = add(target, "p", target.closest("[data-verify]").dataset.caveat);
  caveat.className = "pr-caveat";
}

/** The exact bytes of one link, and the command that reproduces its hash by hand. For the reader
 *  who does not take "your browser checked it" as an answer either.
 *
 *  The bytes get a box of their own with NOTHING else in it. They shared one with the instructions
 *  and the expected hash at first, and a sceptic following the instruction literally — select the
 *  box, paste it, hash it — would have included the instructions in the file and got a different
 *  answer. An invitation to check by hand that fails when someone actually does it is worse than
 *  no invitation, because the reader's conclusion is that we lied. */
function showOneLink(target, body) {
  const link = body.links[body.links.length - 1];
  if (!link) return;
  const wrap = add(target, "div", "");
  wrap.className = "pr-showone";
  const toggle = add(wrap, "button", `Show me the exact text behind call #${link.seq}`);
  toggle.className = "pr-linkbtn";

  const detail = add(wrap, "div", "");
  detail.hidden = true;
  const pre = add(detail, "pre", `${link.prev_hash}${framePayload(body.fields, link.values)}`);
  pre.className = "pr-bytes";
  const how = add(detail, "p",
                  `Everything in that box, saved to a file with no trailing newline, hashes to `
                  + `${link.content_hash} — run shasum -a 256 on it. That is the fingerprint `
                  + `stored against call #${link.seq}, and it begins with the fingerprint of the `
                  + `call before it, which is what welds the sequence together.`);
  how.className = "pr-howto";

  toggle.addEventListener("click", () => {
    detail.hidden = !detail.hidden;
    toggle.textContent = detail.hidden
      ? `Show me the exact text behind call #${link.seq}`
      : `Hide the text behind call #${link.seq}`;
  });
}

// ------------------------------------------------------------------ small DOM helpers
//
// textContent everywhere, never innerHTML: a thesis is text a caller typed, and this panel renders
// it on a page built to be shared widely.

function add(parent, tag, text) {
  const el = document.createElement(tag);
  if (text) el.textContent = text;
  parent.appendChild(el);
  return el;
}

function failure(target, headline, detail) {
  target.hidden = false;
  target.className = "pr-result broken";
  target.replaceChildren();
  add(target, "b", headline);
  add(target, "p", detail);
}

function say(el, text) {
  if (el) el.textContent = text;
}

function setBar(el, fraction) {
  if (el) el.style.width = `${Math.max(0, Math.min(1, fraction)) * 100}%`;
}

function short(hash) {
  const h = String(hash || "");
  return h.length > 20 ? `${h.slice(0, 10)}…${h.slice(-6)}` : h;
}

/** A duration a reader can believe. A one-call record hashes in well under a millisecond, and
 *  "in 0 ms" reads as a number that was never measured rather than as a fast one. */
function howLong(ms) {
  return ms < 1 ? "under a millisecond" : `${ms} ms`;
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}