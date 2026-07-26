# Phase 6 — rework the existing sections · progress report

Date: 2026-07-26 · Branch: `phase/6-sections` · 486 tests pass · 0 lint errors

**All eight sections done.**

---

## Portfolio → Exposure

The criticism was right: a broker shows what you own and what it is worth, better, with real
prices. Exposure answers what a broker cannot — *given what I hold, which live events reach me,
through which holding, by what mechanism?*

Every link names its path, because "you are exposed to Asia" is worthless while "two of your
holdings have live claims naming Asia, here they are" is something you can disagree with.
Concentration is stated as a fact about the list, never a verdict on it.

Tested against the demo account's 26 holdings: it correctly reports that **none** has a live
interpretation attached, and the empty state says *"a real answer, not an empty one"* rather than
manufacturing a connection.

## Calendar

Was one continuous scroll roughly ten thousand pixels tall. You cannot see the shape of a week in a
column. Now month/week/day, Monday-first, importance as visual weight, and consensus/previous/actual
on the day view — which is what makes a release readable *before* it lands. A blank consensus
renders blank, never zero.

## AI Assistant

Six read-only tools instead of a bigger prompt. The registry is a **security boundary**, not a
convenience layer — the model calling these is the same one reading arbitrary ingested text. Three
properties hold by construction, each with a test asserting the *shape* rather than one instance: no
tool can write, none composes SQL from its arguments, none reaches the network or takes a URL.

Asked *"how often are you actually right?"* it calls `track_record` and answers from the Ledger.

## Crypto

Stopped mirroring. Leads with **market structure** — who is leveraged which way, what it costs them
to stay, whether the crowd is building or unwinding — from Binance's public futures endpoints (free,
keyless). Every reading carries the condition that would break it.

**Two calibration errors, both caught only by measuring against live data.** First cut OR-ed retail
account share with funding, so all five majors read "crowded long" at once — including DOGE at
0.06%/yr, which is nothing. Correcting it by raising the threshold went too far: Bitcoin paying ~6%
a year with positioning *building* read as "balanced". Funding is a spectrum, so the reading is now
graded, and account share corroborates rather than triggers.

Also: 11.3s → 17ms via a 300s cache warmed by a scheduler job, and a footer disclaimer that this
change made false ("funding and open interest aren't connected yet") corrected.

## Smart Money → the Ledger

The brief: *"feed all of it into the same claim and Ledger machinery so its signals get scored like
everything else."* Done — and it is the only way the Ledger gets meaningful numbers this decade.

**The Ledger now reads 41% of 282 resolved calls. 115 right, 167 wrong.** Unflattering and real.
The calibration table is the part worth looking at: stated 38% → landed 40%, stated 49% → landed
44%. The system is well calibrated *even though* its hit rate is below half, and those are different
facts.

On backdating, because this is where it could look like cheating: claims carry the signal cluster's
`as_of`, not the import time. That is honest — `signal_clusters` is computed under point-in-time
discipline, so the system really did make that call then. What would be dishonest is presenting them
as things the impact engine reasoned out, so they are marked `convergence-v3` and the Ledger breaks
down **by origin** above every other breakdown. Pooling the two hit rates would make both meaningless.

The 13F reporting lag is now stated at the top of the surface, not in a footnote.

## Morning Brief

Opens by scoring yesterday's calls before telling you anything new — *"6 right and 2 wrong resolved
since yesterday. Running record: 41% of 282"* — with the individual calls and their outcomes, the
misses not buried. Under it, "On the hook today": what is currently open, so a reader can watch it
be scored tomorrow.

Fixed a staleness bug this introduced: the cache key did not include the Ledger, so a claim
resolving would not have busted it and the reader would have seen yesterday's scorecard beside
today's news.

## News → source comparison

The brief asks for *"how differently outlets across regions frame the same event"*. That fell out of
Phase 2's clustering for free — but the view was worthless, because every connected feed was US
financial media. **Two CNBC feeds agreeing is not two perspectives.**

So the fix was source diversity, not code. Seven feeds added, each fetched and parsed first: BBC
Business and World, Guardian Business, Al Jazeera, South China Morning Post, ECB, CNBC
International. Reuters, DW, Nikkei and Arab News were tried and rejected, and that is recorded so
nobody retries them blind.

Then cross-outlet clustering had to work. Measured:

```
0.54  BBC        "Four Palestinians and two Israelis killed"
      Al Jazeera "Funerals held for four Palestinians killed"       SAME
0.33  CNBC       "Amazon cuts jobs in artificial general intelligence"
      BBC        "AI is 'not smart' so what's next in artificial…"  DIFFERENT
```

Any threshold low enough for the first merges the second. **Geography was tried as the corroborator
and is provably wrong** — `geo` is where the *outlet* sits, so BBC (GB) and Al Jazeera (QA) never
overlap. Shared **proper nouns** work: 6/6 on real pairs, no model involved.

The result is the demonstration the brief was describing:

| CNBC (US) | Guardian (GB) |
|---|---|
| "U.S. signs nuclear power agreement with Saudi Arabia" | "Trump gifts Saudi Arabia a nuclear win" |

---

## Journal — the coach gets to see what the trader saw

A journal records what the trader did. It has no idea what was happening while they did it, so the
only thing it can coach on is the outcome — and coaching on outcomes teaches a trader to feel good
about lucky wins and bad about disciplined losses.

So `POST /api/trades` now freezes the Radar as it stood at that moment (migration 028,
`trade_context`): which interpretations were live, ranked by that reader's own relevance, and
whether any named the same instrument, pointing which way. Written once and **never rewritten** —
if a later edit could move the context, the record would drift toward what the trader now
remembers believing, which is the exact bias it exists to counter.

That turns the coach from an outcome scorer into a **process** observer. It can now say *"1 of 6
entries went against a live interpretation"* — a statement about how someone decides, available
long before enough closed trades exist to say whether they are any good.

Three lines held:

**The system is not the benchmark.** The Ledger publishes 41%. Framing "you traded against a live
claim" as a mistake would quietly promote a 41%-accurate machine to the arbiter of a human's
decision, so every pattern mentioning disagreement carries the Ledger's own number beside it — and
states no rate at all when the Ledger is below its own sample floor and has none to publish.

**Sample floors, from both sides.** No pattern below five trades with context; no contrast between
two cohorts unless *both* closed samples clear the floor. Trades without context never enter the
denominator, so six trades of which two carry context is a two-trade sample.

**Constructive, or it does not ship.** A test asserts no pattern is phrased as a verdict — the one
licensed use of "mistake" in the whole module is the denial *"that is a disagreement, not a
mistake"*.

Two things the live data taught, neither guessable from the schema:

- The impact engine does not always write a bare ticker. Real rows read `AMC Entertainment
  Holdings Inc. (AMC)` and `$TSLA`. Exact matching alone silently misses genuine disagreements —
  and a missed match makes the coach report agreement that was never there, which is the failure
  mode that matters. Matching now extracts the ticker; `Treasury bonds` correctly matches nothing.
- Only `kind == "asset"` counts. A claim about semiconductors bears on an NVDA trade but never
  committed to a direction on NVDA, and counting it would invent a disagreement.

Verified live: a short on AMC logged against a 70%-confidence claim saying AMC up records
`alignment: against`, and the trade detail shows the claim that disagreed, by name, with its
confidence and horizon.

Trades logged before capture existed get `capture-context`, which reconstructs from claims whose
timestamps *prove* they were live then — labelled `reconstructed` everywhere it surfaces, because
it is ranked against the reader's frame today rather than the one they had at the time. On the
demo journal it honestly finds nothing: all 8 predate the oldest still-live claim, and the panel
says so rather than manufacturing a connection.

---

## Bugs found and fixed along the way

- The admin-only watchlist was served to anonymous callers (`_require_admin` contract inverted).
- Every account shared one watchlist, addressable by query parameter (B-22, migration 026).
- The prompt-injection fence reassembled the delimiter it removed (found by `/security-review`).
- An internal marker `[convergence:43684:30]` leaked into user-facing Ledger prose (migration 027).
- A missing `Icon` import passed 435 tests and threw on the page — the argument for running the
  browser check as well as the suite.
- **Every model-prose surface was switched off in production and reporting success** (B-23). Six
  call sites gated their model call on `provider in ("gemini", "openai")`, which is False for the
  chain form `gemini,openai` that production actually runs. The signal explanation, the trade
  coach, the journal report and the assistant had all been serving deterministic templates while
  reporting the model had been tried. Found only by asking a running instance what produced its
  prose — no test failed, because the suite runs on `template` by design. Fixed with
  `llm.wants_model()`; a static test now forbids the pattern anywhere in the package.

---

**Status: Phase 6 complete, all eight sections.** The marketing site (Phase 7) is next.
