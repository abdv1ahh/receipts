# Phase 6 — rework the existing sections · progress report

Date: 2026-07-25 · Branch: `phase/6-sections` · 440 tests pass · 0 lint errors

**Seven of eight sections done. Journal outstanding.**

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

## Not done

**Journal.** The remaining section — attach world context at trade time so the coach can identify
behavioural patterns. Specified concretely in `docs/state.md` §"Next steps".

---

## Bugs found and fixed along the way

- The admin-only watchlist was served to anonymous callers (`_require_admin` contract inverted).
- Every account shared one watchlist, addressable by query parameter (B-22, migration 026).
- The prompt-injection fence reassembled the delimiter it removed (found by `/security-review`).
- An internal marker `[convergence:43684:30]` leaked into user-facing Ledger prose (migration 027).
- A missing `Icon` import passed 435 tests and threw on the page — the argument for running the
  browser check as well as the suite.

---

**Status: Phase 6 is 7 of 8.** Journal next, then the marketing site.
