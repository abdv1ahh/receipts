# Cross-check pass — 2026-07-26

Not a phase. The owner read the ten "complete" markers, opened the app, and reported: the site does
not load, the globe does not load, they could not find the marketing site, X does not work, and they
did not know how to connect Reddit. This is what that turned out to be, what was fixed, and what is
still open.

The uncomfortable summary first: **598 tests passed, lint was clean, and six things were broken in
the reader's face.** Every finding below was invisible to the suite. That is the lesson worth
keeping from this pass — the gates that were being run could not see any of it.

---

## What was actually wrong

### 1. The globe was an invisible black sphere — CONFIRMED, FIXED

`globe3d.jsx` set `hexPolygonColor` but never `hexPolygonsData`, and never set `globeImageUrl`.
globe.gl's own documentation is explicit about that combination: with no image "the globe is
represented as a black sphere". A black sphere on a `#05060c` page is nothing at all. The
`globeMaterial={{ color: OCEAN }}` prop was also inert — that prop takes a `THREE.Material`
instance, not a spec, so it was silently ignored and the ocean stayed pure black.

So the surface was drawing a handful of green markers floating in a void with no world behind them.

**Fixed** by vendoring Natural Earth 110m country geometry (public domain, stripped to
`iso` + `name` + coordinates and rounded to 2dp — 488KB → 163KB) into
`frontend/src/world-110m.geo.json` and feeding it to `hexPolygonsData`. It rides inside the
lazy-loaded globe chunk, so the main bundle is unchanged and nobody who never opens the surface
pays for it. `globeMaterial` now receives a real `MeshPhongMaterial`, which meant declaring `three`
as a direct dependency — it was always installed as react-globe.gl's peer, this only stops the
import being implicit.

Clicking a landmass now selects that country, so a country with no events is selectable too.
Previously only event markers were clickable, which meant *checking whether a country is quiet* was
impossible — the exact question the surface exists to answer.

**Verified** in headed Chromium with real WebGL, not headless. This matters: headless Chromium has
no GPU, the component correctly falls back to the flat map there, and so a headless "no console
errors" check reports success against a globe that never rendered. That is how this survived a phase
that claimed to have checked it.

### 2. Every page scrolled sideways on a phone — CONFIRMED, FIXED

All 21 surfaces overflowed at 375px, most by ~190px. This is the bulk of "so many visual glitches".

Causes, in order of blast radius:

- **The top bar.** Eight fixed-width controls in a flex row that stopped fitting below ~720px and
  pushed every page wider than the viewport. The search field is now replaced by a search *button*
  below 720px (there is no ⌘K on a phone, so hiding the field outright would have removed search
  entirely).
- **`1fr` grid tracks.** A bare `1fr` is `min-width: auto` and refuses to shrink below its content.
  Fixed to `minmax(0, 1fr)` in the calendar, dashboard, Smart Money and watchlist grids — and in
  four places on the marketing site.
- **An unbreakable URL.** One ingested news item whose title was a raw `drive.google.com` link
  widened its container past the viewport. `.content` now sets `overflow-wrap: anywhere`
  (`anywhere`, not `break-word` — only `anywhere` also shrinks min-content, which is the half that
  stops the overflow). Ingested text is arbitrary by definition, so this is handled at the root
  rather than by guessing which card can receive a URL.
- **Wide tables** now scroll inside their own panel below 1000px.
- **`.bt { white-space: nowrap }`** on a 274px badge — correct on desktop, wider than a phone card.

A self-inflicted trap worth recording: the first attempt put the narrow-screen block near the top of
`styles.css` and it silently lost, because **a media query adds no specificity** and the base rules
further down the file won on source order. The block now lives at the end of the file under a
comment saying it must stay there.

**Verified**: 21 surfaces × 375 / 768 / 1280px, zero overflow, plus the marketing site.

### 3. The marketing site was unreachable — CONFIRMED, FIXED

It was built, good, branded, and running on live data at `/site/` the whole time. Nothing linked to
it, and `/` served the app's own landing page, which still pitched the **pre-rebrand** product
("TradeOSS — the AI trading terminal", smart-money convergence, a trader community). A stranger
arriving at the front door got a page describing a product that no longer exists.

`/` now 307s to `/site/` for anyone without a session cookie (cookie *presence*, not validity — no
database round trip for a routing decision, and an expired cookie lands on the app, which asks you
to sign in, which is right anyway). Signing out returns to `/site/`. The old `LandingView` is
deleted along with `ExploreView`, which was imported by nothing and linked to a `community` surface
that no longer exists.

### 4. The rebrand had only ever reached the nav bar — CONFIRMED, FIXED

`BRAND_NAME` exists and `config.brand_name()` returns "Rhumb", and **almost nothing called it**.
Fourteen user-facing strings across nine frontend files and twelve backend strings still spelled out
"TradeOSS" — the disclaimers under every signal, the pricing copy, the AI assistant's model label,
the journal's analysis footer, the alert emails, and the `<title>` and meta description of the app
itself (which is what a shared link previews as).

There are now exactly two homes for the name: `config.brand_name()` and `frontend/src/brand.js`.

### 5. X / Twitter — CONFIRMED UNFIXABLE AS ASKED, ANSWERED PROPERLY

X has no free read tier. That has not changed and is not going to. Scraping is against their terms
and breaks constantly. This is the one thing in the brief that cannot be built as written, and
Appendix A of the brief says so itself and names the substitute.

**Bluesky is now a real source**, which was listed as an open gap and had never been built:

- 16 curated consequential accounts (wire services, non-Western outlets, and the research
  institutions that explain mechanisms), each **verified against the live API before seeding** —
  no handle was guessed, and candidates that turned out to be squatted or non-existent were dropped.
- Keyless. `~350` events ingested on the first pass, 0 failures, and the hourly `interpret` job has
  already produced scored claims from them.
- Reposts are skipped: an account amplifying someone else is not that account speaking, and treating
  those as identical would put words in a central bank's mouth.
- `geo` is left empty, because geo means where an event *lands*, not where the publisher sits. A
  test enforces this on the new source specifically, since it is the most repeated mistake here.
- 14 offline tests against a real captured payload.

Measured while building it, and worth knowing before anyone tries: `app.bsky.feed.searchPosts`
returns **403** without authentication now. Network-wide keyword search is closed. `getAuthorFeed`
and `getProfile` are keyless. So this reads a curated list rather than searching — which is what the
brief wanted from a social source anyway.

The X entry stays visible on the integration page rather than being quietly dropped, and now names
what covers the need instead of reading as a dead end.

### 6. Reddit — WORKING AS DESIGNED, THE SETUP PATH WAS THE PROBLEM

The adapter is correct and the degradation panel already linked to the right page. What was missing
was everything between "I clicked the link" and "it works": Reddit's form demands a redirect URI it
never uses, the client id is the unlabelled string *under* the app name, and there was no way to
tell whether a pasted key worked.

New `cli check-source <key>` makes a real call and reports plainly — `OK`, `NOT CONFIGURED` with the
exact variables and where to get them, or `UNAVAILABLE by design` with the reason. It never echoes
the credential, because httpx puts the full URL in exception text. The Reddit note now gives the
exact steps including the two gotchas.

---

## Found along the way

- **GDELT was invisible to the operator.** It has been running hourly and producing events, and it
  was not in `sources.py`, so it appeared nowhere on the integration status page — which the brief
  requires for every source, and which is the page that exists precisely so the owner never has to
  guess why a panel is empty. Now registered.
- **The RSS entry listed 4 feeds; there are 11.** The hand-kept copy had drifted. It is now derived
  from `news_rss.FEEDS`, so it cannot drift again.
- **`spine.upsert_event` never wrote `author_influence`**, despite `watchlist_accounts.py`
  documenting that module as the place it is stored. No source had ever supplied one, so the
  documented behaviour had simply never run. Bluesky is the first source that supplies it; now
  persisted.
- **A redundant hamburger sat in the desktop top bar**, because `.menu-btn { display: none }` lost
  to `.icon-btn { display: grid }` declared after it. Same class of bug as the media-query trap.
- **Dead code removed**: `LandingView`, `ExploreView`, `fetchCommunityFeed`, and 14 lines of
  orphaned landing CSS. Bundle: JS 376.2 → 373.5 kB, CSS 106.2 → 105.5 kB.

---

## What is still open

Honest list; none of it is newly broken, and none was introduced by this pass.

- **Reddit, YouTube, OpenFIGI, SMTP and Google OAuth still need keys.** Only the owner can create
  them. `check-source` will now confirm each one the moment it is set.
- **Google sign-in has still never been run against Google.** The validation logic is tested; the
  handshake is not.
- **SMTP is still unconfigured**, so alert digests and password resets queue rather than send. The
  app refuses to half-send, which is the right failure, but it is still a gap before real users.
- **`/code-review` has never been run on any phase diff**, including this one.
- **The `community` backend module is orphaned in the UI.** Its last frontend caller
  (`ExploreView`) is now deleted, but the module, its API routes and its tables remain. I did not
  delete a whole feature on my own judgement — **this is a question for the owner**: is the
  community surface dead, or parked?
- **The 3D globe is verified on desktop WebGL only.** The flat-map fallback is exercised (that is
  what headless renders), but no real low-power mobile device has been tested.
- **`author_influence` is stored but not yet used in ranking.** It reaches the events table; nothing
  reads it back into relevance scoring yet.

---

## The gate that would have caught all of this

Not "write more tests" — the failures were not test-shaped. Specifically:

1. **Check a running instance at 375px.** Every layout bug here was one browser resize away.
2. **Check WebGL surfaces in a headed browser.** Headless has no GPU and will report a clean
   fallback as success.
3. **Grep the built bundle for the old brand name** before calling a rebrand done.
4. **A new ingestion module is not finished until it has a `sources.py` entry.**

These are now in `CLAUDE.md` as gotchas 0c, 0d and 0e, and in the sources section.

---

# Follow-up pass — same day

The owner's instruction after reading the above was "whatever has not been done it needs to be
done". Four decisions were taken by them; everything else below is work.

## Their rulings

- **Community: rebuild the UI.** Not deleted.
- **Short interest: keep it parked.** Now says so in `config.short_interest_enabled()`, so the next
  cleanup pass finds a note instead of an orphan.
- **Cleanups: action all three.** Two turned out to be stale audit entries (see below).
- **Keys: set up all four.** Runbook written at `docs/runbooks/keys.md`.

## Community, rebuilt rather than restored

`community.py` (Slice F) was complete and tested the whole time; it lost its surface when the
discovery hub linking to it was deleted as dead code. The new `/community` has a public feed, a
Following feed, a track-record leaderboard, and a profile editor, plus addressable trader pages at
`/trader?handle=x` — a track record nobody can link to is not much of a record.

Verified end to end in a browser: follow (followers 1 → 2), like (0 → 1), comment posted and
deleted, Following populating only after a follow. Test data cleaned up afterwards.

The leaderboard ranks by **win rate over public closed trades**, never by a return figure, and
shows nobody at all below the sample floor rather than ranking someone on four trades. Both rules
are printed on the surface.

## The six audit rulings, resolved — three of them were wrong

- **A-01 short interest** — kept, parked, documented.
- **A-02 ENABLE_CONGRESS** — removed, plus migration 033 dropping the seed row.
- **A-03 Stripe price ids** — **the audit was wrong.** It claimed nothing reads them; `billing.py`
  reads them through a `price_id_env` lookup that a literal grep missed. Live config, kept.
- **A-04 share cards** — kept, and its outbound link fixed (it pointed at `/`, which now redirects).
- **A-05 `uploads/`** — already gone.
- **A-06 `test_gemini.py`** — **no such file.** The real one is `test_explain_gemini.py`, correctly
  named for the module it tests. Nothing to rename.

Three of six entries in a document written to find stale claims were themselves stale. Worth
remembering when reading any audit here, including this one.

## `author_influence`: stored, and now actually read

`watchlist_accounts.py` has always documented the spine as the place a source's editorial weight is
stored. `spine.upsert_event` never wrote the column, and nothing read it back — invisible because no
source supplied one until Bluesky. Now written, backfilled onto the 110 older Bluesky events from
their stored payloads, and folded into `relevance.score` as an `authority` part weighted 0.08.

Deliberate choices: a claim with no author scores the NEUTRAL default, so an SEC filing is not
penalised for lacking a byline; authority is the smallest weight, because who said something is
evidence about it rather than a substitute for what it says; and a test asserts a maximally
authoritative but irrelevant claim still ranks below a quiet one that touches your watchlist.

## What the two quality gates actually found

**`/security-review`** — one real issue, in code from the earlier pass. Making `auth_error` render
(it never had) meant anyone could send a victim `/auth?auth_error=<any text>` and have arbitrary
official-looking wording appear on the genuine login page; separately `_fail(str(exc))` reflected
internal exception detail through the URL. React escaped the HTML so it was never XSS, but it was a
clean phishing surface on our own domain. **Fixed at the root**: the handler emits a short code, the
client owns the wording and renders only codes it recognises, and the exception detail is logged
server-side. The pre-existing test that asserted the old escaping now asserts the stronger property.

**`/simplify`** — one real bug. `pct` existed as near-identical copies in three surfaces; the fourth
copy, in the new community feed, omitted the ×100. `trades.realized_pnl_pct` returns a fraction, so
a +10% trade was being published to other people's screens as **"+0.1%"**. Formatters now live in
`frontend/src/format.js`, used by journal, portfolios and community, and both surfaces now agree.
Also added: the Bluesky adapter was missing the hostname-allowlist check that gdelt, prices and
reddit all perform — added, with a test.

Both gates were run by me reading the diff directly rather than by fan-out agents.

## Still open

- **The four keys are the owner's to create.** Nothing else blocks on me.
- **`/code-review` has still never been run** on any diff here.
- **`/security-review` has never covered the code predating this branch** — it has only ever seen
  diffs. Phase 9 §"What is NOT fixed" remains the honest list.
- **The backup cron line is still not installed.** `scripts/backup.sh` works; nobody schedules it.
- **The 3D globe is verified on desktop WebGL only** — no real low-power mobile device.
- **Cluster matching does not scale, and adding a high-volume source made it visible.**
  `spine.find_cluster` computes `similarity(c.title, ...)` against every cluster in the time window
  — 821 of them now — for every event, with no trigram index. Measured: 186s for 381 events, 165s
  for 183. The cost tracks the CLUSTER CORPUS, not the batch, so shrinking the fetch window barely
  helped and the pass will get slower as the corpus grows. It is comfortably inside its hourly
  interval today and nothing is broken.

  The fix is known but not safe to do in passing: a GIN trigram index on `event_clusters.title`
  only helps the `%` operator, and `%` takes its threshold from the `pg_trgm.similarity_threshold`
  session GUC rather than from the query. Done right it is `title % $1 AND similarity(...) >= $2`
  with the GUC set at or below WEAK_SIMILARITY, so the index prunes and the explicit check keeps
  the semantics identical. Done wrong it silently stops matching things, in the one piece of logic
  this whole product is built on. It needs a before/after comparison of real clustering output,
  which is a task of its own.

- **Bluesky addresses accounts by handle, not DID**, so a renamed account fails and is logged by
  name. Fine for 16 curated institutions; revisit if the list grows or starts tracking individuals.

---

# Marketing site pass — the accuracy problem

The owner's report: "it literally markets in some section in a way where our application is not
even useful, and if that is true then there's no use of this application because it's more often
than not wrong."

That reading was correct, and the underlying situation was worse than a wording problem.

## What was actually on the page

The accuracy section carried the H2 **"We are wrong most of the time."** above 41%, 115 right, 167
wrong. The footer repeated it: "it is wrong more often than it is right". A visitor's conclusion —
this does not work — was the only available one.

## What the number actually was

Three facts, each verified against the database rather than the docs:

1. **All 282 resolved calls are `convergence-v3`** — the legacy smart-money signal. Not one is from
   the impact engine.
2. **The impact engine, which is what the entire site sells, has 80 open claims and zero resolved.**
   It has no accuracy figure at all.
3. **The signal shows no demonstrated edge — which is not the same as "it fails", and I got this
   wrong the first time.** 115/282 is 40.8%, and the *frequency* is genuinely 3.1 standard errors
   below a coin flip. But the *return* is not: mean excess is −1.52% per call with a 95% interval
   of **[−3.80%, +0.76%], which spans zero**. The two statistics disagree because the wins are
   larger than the losses (+15.9% against −13.5%), so the returns cancel. My first pass reported
   the point estimate as proof of failure and put that on the marketing site. It was an overclaim,
   it is corrected below, and it is the same error the page was already making in the other
   direction: **a number without an interval invites whatever verdict the reader arrives with**.

So the page took one subsystem's failing record, published it under the heading "the accuracy
record", and placed it beneath a hero describing a different subsystem. It was discouraging *and*
inaccurate about the thing it appeared to describe.

## The missing statistic

The Ledger reported a hit rate and no magnitude, and a hit rate alone is misleading in both
directions: 40% right with winners twice the size of losers is a good record, and 60% right with
large losers is a bad one. `ledger.summary()` now returns `avg_excess_on_hits`,
`avg_excess_on_misses` and `expectancy`, and both the app's Ledger and the marketing site show it.
For this signal it makes the record look worse, which is exactly the argument for having it.

## What the site says now

- The H2 is **"Every call is scored, including the bad ones."** The promise is the commitment —
  written down before the outcome exists, uneditable, scored whichever way it goes.
- **The two planes are separated on the page and cannot be confused.** The engine's block says
  plainly that 80 interpretations are open, none has resolved, and there is nothing to show yet —
  rather than borrowing a number to fill the space.
- **The signal plane's block publishes its full record including the −1.5% expectancy**, and says
  in words that following it would have trailed SPY.
- **Calibration is given its due**, because it is the one measure that comes out well: it stated
  38% and 40% happened, so it does not claim more certainty than it earns.
- The walkthrough's already-marked example is **labelled as the signal plane**; it previously sat
  unlabelled under a world-event walkthrough, implying the engine's calls were being scored.
- A new FAQ answers the question directly: *"So how accurate is it, actually?"*
- The footer no longer asserts the product is wrong more often than right.

**This is a question for the owner, not something I decided.** The smart-money convergence signal is
significantly worse than chance and has negative expectancy over 282 resolved calls. It is still
shipped in the app as "Smart Money Score" and still generates alerts. Publishing its record is
honest; continuing to surface it as a signal to act on is a product decision worth making
deliberately. Being reliably worse than chance is itself information — but that is an argument for
investigating the mapping, not for leaving it on the dashboard as-is.

## Motion

The brief offers GSAP ScrollTrigger with Lenis, or Framer Motion, then sets a first-contentful-paint
target of 1.5s two paragraphs later. None of those libraries is here, because the platform now does
this natively: `animation-timeline: view()/scroll()` runs the whole parallax on the compositor with
zero JavaScript. Where a browser lacks it, one passive listener writes two custom properties per
frame and the same CSS reads them — one listener for the page, not one per element. Everything
animated is transform or opacity only.

What moves, and why it is that and not something else:

- **Three depth layers in the hero.** A new chart graticule sits furthest back (meridians fanned
  from a vanishing point, parallels bowed — a projection, not graph paper), the wind rose mid, the
  content in front. Parallax needs something to have parallax *against*.
- **The rose is a compass card and it swings 60° across the page.** A rhumb line is a course held
  at a constant bearing; that is the definition and it is what the product is named after.
- **A live bearing readout in the nav**, sweeping N 000° → NNE 060°, driven by the same page
  progress as the rose — verified in the browser to agree to within 0.05°. The card you watch turn
  and the number reporting it are one instrument.
- Smooth-scroll hijacking is deliberately not done. It takes scrolling away from the OS, breaks
  trackpad and keyboard feel, and fights assistive tooling.

Reduced motion: every animation rule sits inside `prefers-reduced-motion: no-preference`, verified
structurally rather than by eye — which matters here, because scroll-driven animations ignore the
duration override in `shared/tokens.css` and would otherwise have survived it. The JS driver and the
bearing both no-op. The bearing still renders its course, held, rather than vanishing.

Checked at 375 / 768 / 1440px at six scroll depths each: no horizontal overflow anywhere.

## Accessibility, found in the same pass

- **Heading order was broken on the marketing site**: `h1` in the hero, then `h3` for each live
  claim, with no `h2` between them. The live panel's own label is now an `h2`, which is what it
  always was semantically. Eighteen headings, no jumps.
- **The faintest text failed contrast on both front ends.** The site's `--paper-faint` measured
  **4.16:1** and the app's `--faint` measured **3.10:1**, against a 4.5:1 AA floor for normal text —
  and the brief asks for "contrast that passes". Raised to 5.0:1 and 5.4:1 on the page background
  respectively, measured against every surface each token actually lands on rather than only the
  easy one. The app's token stops one step short of clearing the transient row-hover background,
  because the next value up collides with `--muted` and collapses the type hierarchy; that
  trade-off is written into the token's comment rather than left for someone to rediscover.
- The FAQ accordion was already a real `<button>` with `aria-expanded` and `aria-controls`, the
  country picker already carried a role and a label, and `FAQPage` structured data was already
  present and valid. Those needed nothing.

---

# "Make the signal work" — what is and is not possible

The owner's instruction after the above: make it work.

## The correction that came first

Investigating in order to fix it turned up that my own diagnosis was overstated. Setting out the
three statistics properly, because they do not all say the same thing:

| statistic | value | conclusive? |
|---|---|---|
| directional hit rate | 40.8% of 282, z = **−3.10** | **yes** — these names fell more often than they rose |
| mean excess per call | −1.52%, 95% CI **[−3.80%, +0.76%]** | **no** — the interval spans zero |
| average win / average loss | +15.9% / −13.5% | this is why the two disagree |

So the sample establishes that the signal picks names that decline more *often*, and simultaneously
fails to establish that following it loses money, because the rarer wins are bigger. Reporting
"−1.52% expectancy" as a verdict was wrong of me, and it went onto the marketing site before it was
caught. Both are fixed.

## Why it cannot be tuned into working right now

The obvious move is to search for a subset that performs. Doing that found one: clusters with 4–6
independent filers show +1.56% at 30 days against −2.23% for the 3-filer bulk. It is worthless:
t = 0.76, which is noise, and it was found by trying five subsets on one sample. Shipping a filter
chosen because it backtests well, on a product whose entire argument is that it does not flatter
itself, would be the precise dishonesty this codebase exists to avoid.

The confidence buckets look genuinely mis-specified — at 90 days "high" runs −25.8% against
"medium" at +9.5%, an inversion — but n = 8 in that bucket. It is a suspected defect, recorded as
one, and not something to refit on eight observations.

## What actually limits it, and what was done

The sample is not small because the data is exhausted. Counted:

- **17,145 signal clusters**, which the backtest collapses to **583 distinct episodes**;
- of those, 270 are still open at 30 days, 402 at 90, 530 at 180 — most horizons have not closed;
- **271 distinct tickers, 268 with price history** — price coverage is *not* the constraint;
- **Form 4 goes back to 2010** (664,923 rows) but **13D/G only to 2024-07** (51,099).

That last line is the binding constraint. The convergence signal needs clustered filings across
both sources, so the two-year 13D/G window caps the whole history at ~28 episodes per month. To
reach the ~1,470 resolved calls needed to detect a 1% per-call edge takes roughly four more years
of filings — which SEC EDGAR has and this database does not.

Measured cost: **~24 seconds per month** of 13D/G backfill. A 2021→2024 backfill is therefore about
twenty minutes of wall time, not an overnight job, and it was started. Extending to 2018 is another
half hour. That is the concrete path from "we cannot tell" to "we know".

## The actual product fix

The Ledger now reports whether its own numbers mean anything:

- `mean_ci` — the mean with a 95% interval and a `significant` flag that is False whenever the
  interval spans zero;
- `proportion_z` — how many standard errors a hit rate sits from a coin flip;
- `sample_needed` — how many resolved calls it would take to detect a given edge at the measured
  dispersion. This is the number that turns "not enough data" from an excuse into a plan.

All three are pure and tested offline. Both Ledger surfaces publish the interval beside the point
estimate, and the marketing site now states plainly that on this sample nothing is shown either
way, and how many calls it would take to find out.

That is the honest answer to "make it work": **the signal has not been shown to fail, the record was
never able to tell the difference, and now it can.** The remaining work is sample, and the sample is
a backfill away.

## Three silent blockers, found by trying to grow the sample

"Make it work" turned out to mean "find out why it cannot be measured". The signal's history was
capped at ~583 episodes not by the data, but by three defects that each failed *quietly* — no
error, no failed test, exit code zero.

### 1. EDGAR spells the form two ways, and only one was matched

Measured against the live daily index on 2026-07-26:

| index | form types present |
|---|---|
| `master.20230515.idx` | `SC 13D`, `SC 13G`, `SC 13D/A`, `SC 13G/A` |
| `master.20250515.idx` | `SCHEDULE 13D`, `SCHEDULE 13G`, `SCHEDULE 13D/A`, `SCHEDULE 13G/A` |

`schedule13.FORM_TYPES` contained only the modern spelling — with a comment asserting it was the
right one. Every backfill before the SEC's 2024 modernisation therefore logged *"0 Schedule 13D/G
filings in index"* and succeeded. **Fourteen years of filings skipped with no error.** One 2023 day
that previously yielded nothing now yields 98 filings. Legacy spellings normalise to the modern one
so the stored rows keep a single vocabulary, and five tests hold it — including that a 2023
activist filing still classifies as activist rather than losing that status to spelling.

### 2. A lint fix silently disabled signal computation

`compute-signals` refuses to run unless `convergence.py`'s hash matches the registered definition —
a good guard (decision #24), protecting against a signal silently changing meaning. It had been
refusing since **2026-07-25**, because the Phase 1 lint pass removed an unused `timezone` import
from that module. One line, no thresholds or weights touched.

The guard was right to fire and nothing surfaced that it had. Verified the diff line by line, then
registered v4 with a changelog stating plainly that there is **no behavioural change**. This is the
same failure family as B-23 in `docs/bugs.md`: a correct mechanism whose refusal nobody could see.

### 3. The liquidity floor had no prices to stand on

v3 added a point-in-time liquidity floor (90-day median dollar volume above $2M). `prices_eod` began
at **2024-04-01**, so every historical `as_of` failed the floor and published nothing. Backfilled to
2021-06-01; ~50,000 deep rows added.

### What is left, with its measured cost

Insider history is shallow too, and `min(knowable_time)` reads 2010 only because of a **single
outlier row** — which is what made my earlier "Form 4 goes back to 2010" claim wrong. The real
distribution starts in 2024. Clusters need insider *and* stake filings together, so 13D/G history
alone produces no candidates.

Measured: **one week of Form 4 backfill takes over ten minutes**, so 2.5 years is a twenty-hour job.
That is the remaining work and it is time, not engineering — the three defects that made it
*impossible* are fixed. `make backfill-full` is the command; it should be run overnight, then
`compute-signals`, `run-backtest` and `import-signals` in that order.

**What this changes about the verdict.** The signal was never measured on enough data to judge, and
three separate bugs guaranteed it never would be. It still has not been shown to work. It has also
never been given the chance, and the Ledger can now tell those two apart.
