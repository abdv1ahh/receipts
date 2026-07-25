# Phases 3 & 4 — the impact engine, the Ledger, and Radar · progress report

Date: 2026-07-25 · Branch: `phase/3-claims` · 3 commits · 349 tests pass · 0 lint errors

Phases 3 and 4 are reported together because Radar is the visible surface of the claims Phase 3
produces; splitting them would have meant shipping an engine with nowhere to look at it.

---

## What exists now that did not before

**A claim.** The product's actual output: how an event propagates, what it touches, over what
horizon, with what confidence — timestamped when made so it can be scored later.

**A ledger.** Not a separate store: claims joined to outcomes. There is deliberately no second
copy of the record that could drift from, or flatter, the first.

**A personal frame.** Ten hand-curated country rows, each with a source, that make the same event
read differently from Sharjah than from São Paulo.

**Radar.** The primary surface. A signed-in reader now lands here, not on the dashboard.

---

## The two rules that shape everything

### A mechanism must name a channel

`mechanism_is_specific()` rejects prose that states a direction without a causal channel. *"This
is bullish for oil"* fails. A chain naming rerouting, added voyage days and delivery-basis
tightening passes.

This one check is the difference between this product and a headline aggregator, and when it
fails **the engine writes nothing at all**. There is no deterministic template fallback here —
deliberately, and unlike every other AI path in this codebase. A template cannot reason about
causation, and a fabricated claim inside a ledger that exists to measure honesty would poison the
only thing that makes the product defensible.

### The validator is also the security boundary

Phase 2 made the spine ingest arbitrary internet text. A news article can contain text crafted to
hijack the model. So: content is fenced in delimiters, **the delimiters are stripped from the
content first** (otherwise a crafted article closes the fence early and the rest reads as trusted
instruction — that is the whole attack, and it is one line to prevent), and the returned structure
is validated field by field with unknown keys dropped. An injected instruction cannot produce an
arbitrary output shape, because a shape that does not validate is discarded entirely.

---

## Four things only real data and a real model would have shown

**1. Azure's content filter classified our own prompt-injection defence as a jailbreak.**

The instruction quoted example attack phrases so the model would recognise them. Azure's filter
read that as an attack and rejected **every** request with a 400 and
`"jailbreak": {"detected": true}`. Our defence made the provider unusable.

The instruction now teaches the rule in the abstract, a test asserts no attack strings return, and
`llm.py` reports a content-filter rejection as a **refused prompt** rather than a generic
transport failure — retrying never helps, and the caller needs to know which it was.

**2. The engine reads clusters, not events.** Measured on real data: an RSS summary averages 125
characters and an 8-K description 66. Asking a model for a causal mechanism from a headline and
one sentence is asking it to invent one. A cluster carries every member's text and, more usefully,
several independent framings of the same happening.

**3. `mechanism: null` is success, not failure.** The model declining thin content is the system
working as instructed. Reporting that as "named a direction, not a channel" would send an operator
hunting a prompt bug that does not exist. The two are now distinguished.

**4. `= ANY(%s::record[])` does not work.** psycopg cannot bind an anonymous composite type.
Contradiction linking is now two parallel arrays unnested together.

---

## Verified end to end

Six real claims generated from the live spine. One of them independently produced the brief's own
Strait of Hormuz example — *"a critical maritime route for oil shipments… disruptions lead to
increased shipping times and costs, tightening the supply of oil"* — from a real event, without
being prompted with it.

Measurement was checked against **real price history** by backdating claims onto known moves:

| subject | said | excess vs SPY | verdict |
|---|---|---|---|
| ABCL | up | +19.7% | hit |
| ABR | down | −31.3% | hit |
| ABT | down | −6.5% | hit |
| ABG | up | −4.4% | **miss** |
| EURUSD | up | — | **unscoreable** (no price series) |

Calibration read stated 0.70 against observed 0.75. **Those synthetic claims were then deleted** —
test rows inside an honesty ledger would defeat its entire purpose.

---

## Design decisions worth recording

**Excess return, not raw.** A claim that said "up" during a week when everything rose has
demonstrated nothing.

**A noise floor.** A move under 2% excess is `inconclusive`, not a hit. Counting small moves as
hits is the easiest way to inflate a track record, so it is refused explicitly.

**`unscoreable` is a counted verdict, not a silent drop.** Currencies and regions have no price
series here. Excluding them quietly would let the hit rate be computed over a self-selected
sample — exactly how track records get flattered.

**The Ledger leads with misses.** They appear above the breakdowns. A slice with too few resolved
calls shows its count, never a percentage: 2 of 3 must never render as "67% accurate". Calibration
is shown as stated-versus-observed, because "we said 70% and it landed at 68%" is the honest
question a hit rate alone cannot answer.

**Radar leads with the consequence.** The mechanism is the largest text on the card; the source
headline sits underneath as provenance. A reader came to find out what something *means*, not to
re-read a headline. Confidence is always visible, `contradicts` is surfaced rather than smoothed
into one confident narrative, and every card says why *it* is in front of you.

**Country selection sits on Radar, not in settings**, because setting it is what converts a
generic feed into a personal one.

**"On the radar" on the dashboard** was showing the next few calendar entries — a schedule, not a
radar, since nothing on it could ever be a surprise. It now previews the real Radar. The calendar
data moved to its own tile, honestly renamed "What's coming", which is what it always was.

---

## A bug found in existing code

**B-22: every user shares one watchlist, selectable by query parameter.** `watchlists` is keyed by
a free-text `user_key` defaulting to `'demo'`, and `/api/watchlist` takes that key as a query
parameter with no session check. Pre-existing, not introduced here. Logged in `docs/bugs.md`;
Phase 8 re-keys it to `user_id`, Phase 9 tests the boundary.

---

## What I could not do

- **The Ledger has no hit rate yet, and cannot.** Its claims are hours old and the shortest horizon
  is five trading days. The surface correctly reports "6 live interpretations waiting" rather than
  inventing a number. Real accuracy data needs calendar time to exist — this is the one thing in
  the project that cannot be accelerated.
- **Phase 4 is not complete.** Saved filter sets, in-place threading of developing stories, and
  subscribable alerts are specified in the brief and not built. The Radar surface, its ranking,
  filters, reasoning expansion, and the dashboard tile are.
- **GDELT still has not been observed ingesting** — carried from Phase 2. My own early unpaced
  probing throttled this IP; the adapter and its backoff are verified, a live ingest is not.
- **`/simplify` and `/code-review` were not run** on this diff. `/security-review` ran on Phase 1
  and found a real vulnerability; it has not run on Phases 2–4.
- **Gemini's free tier is exhausted for the day.** The provider chain correctly fell through to the
  fallback, which is how the content-filter bug surfaced at all. Claims currently generate on the
  fallback provider.

---

## What I need from you

Nothing blocking. Phases 5–9 (globe, section reworks, marketing site, accounts and deployment,
security) remain.

The one thing worth doing when convenient: an **OpenRouter free key**
(<https://openrouter.ai/keys>) would give the chain a second healthy provider, since Gemini's daily
free allowance is now a real constraint on how many claims can be generated per day.

---

**Status: Phase 3 complete. Phase 4 core complete** (Radar, ranking, dashboard tile); threading,
saved filters and alerts outstanding.
