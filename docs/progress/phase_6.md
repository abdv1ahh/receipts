# Phase 6 — rework the existing sections · progress report

Date: 2026-07-25 · Branch: `phase/6-sections` · 401 tests pass · 0 lint errors

**Partial.** Three of the eight sections are reworked. The rest are listed at the bottom with what
each still needs.

---

## Portfolio → Exposure

The owner's criticism was right, and worth restating precisely: a broker already shows what you own
and what it is worth, better, with real prices. Building a worse version of that was the problem.

Exposure answers the question a broker cannot: **given what I hold, which live events reach me,
through which holding, and by what mechanism?**

Every link names its path. "You are exposed to Asia" is worthless. "Two of your holdings have live
claims naming Asia, here they are" is a statement you can disagree with — and being disagreeable
with is the only property that makes it worth showing.

Two rules I held to:

- **Concentration is a fact about your list, never a verdict on it.** The product does not know
  your circumstances and does not get to tell you your risk is wrong.
- **Corridors need a home country.** A corridor with one end missing is a line to nowhere, so it
  is not drawn and the surface says why.

Verified against the demo account's 26 holdings: it correctly reports that **none** of them has a
live interpretation attached, because the six claims currently in the store name sectors and
regions rather than those tickers. That is the right answer, and the empty state says so — *"a
real answer, not an empty one"* — rather than manufacturing a connection.

## Calendar

It rendered ten days of earnings as one continuous scroll roughly **ten thousand pixels** tall.
That is a list. A list cannot answer the question people open a calendar to ask — *what does my
week look like* — because you cannot see shape in a column.

Now month, week and day views over the same data. Monday-first, because a trading week is not
Sunday-first anywhere this product runs. Importance is encoded as visual weight rather than hidden
in a chip, the filter actually reduces what you see, and the day view surfaces
consensus/previous/actual, which is what makes a release readable *before* it lands.

A blank consensus renders blank, never zero. 2,560 events across 45 days, no console errors.

## AI Assistant

The brief was specific — tools, not a bigger system prompt — so: six read-only lookups
(`search_events`, `search_claims`, `track_record`, `country_exposure`, `smart_money`,
`data_coverage`). The model picks up to three, they run, and it answers from what came back.

**The tool registry is a security boundary, not a convenience layer.** The model calling these is
the same one reading arbitrary internet text ingested in Phase 2. Three properties hold by
construction, each with a test asserting the *shape* rather than one instance:

- No tool can write — no `INSERT`/`UPDATE`/`DELETE` anywhere, and no generic query escape hatch to
  add one by accident.
- No tool composes SQL from its arguments. The model picks a tool and fills in blanks that are
  clamped here; it never writes a query.
- No tool reaches the network or accepts a URL. An injected instruction telling the assistant to
  fetch an address has nothing to call.

Hallucinated argument names are dropped before the call. A failing tool returns an error rather
than raising, so the assistant can say a lookup failed without the whole answer failing.

`smart_money` states the **13F reporting lag in every response**. A holding can be 45 days stale by
the time it is public, and an answer omitting that is misleading even when every number is correct.

**Verified live.** Asked *"how often are you actually right?"* it called `track_record` and
answered that there is no data yet — n=0, hit rate null, insufficient sample — then explained the
excess-vs-SPY methodology. That is the brief's requirement met literally: *"Asked about its own
reliability, it reads the Ledger and answers honestly."*

---

## A latent bug the wiring exposed

`answer()` had a local variable named `llm` shadowing the module import, so every tool-path request
raised `UnboundLocalError`. It only surfaced because the new code needed the module. Renamed.

---

## Not done in this phase

| Section | What it still needs |
|---|---|
| **Morning Brief** | Fold in yesterday's Ledger outcomes and changes to existing claims, so the reader sees the system held to account daily. The brief also wants it deliverable by email on a schedule. |
| **Smart Money** | Feed its convergence signals into the claim/Ledger machinery so they are scored like everything else. The 13F lag is now stated in the assistant tool but not yet on the surface itself. |
| **News** | Fold into the impact engine, plus the source-comparison view (how differently outlets across regions frame the same event, and where coverage is unusually thin). The spine's clustering already groups by source, so the data is there. |
| **Crypto** | Still a data mirror. Needs on-chain flows tied to events, exchange reserves, funding rates read against news flow, and scenario analysis with explicit invalidation conditions. |
| **Journal** | Attach world context at trade time — what the Radar was showing, which claims were live — so the coach can identify genuine behavioural patterns. |

I would rather report three sections done properly than eight touched.

---

## Carried, unchanged

- **GDELT** is in a six-hour backoff of its own making; the adapter is correct and tested.
- **The Ledger has no hit rate** and cannot until horizons elapse. Six claims are open.
- **`/simplify` and `/code-review`** have still not been run on any phase diff.
  `/security-review` has now run twice and found a real vulnerability each time.

---

**Status: Phase 6 partial** — Exposure, Calendar and the Assistant are done; five sections remain.
