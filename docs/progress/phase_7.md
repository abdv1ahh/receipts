# Phase 7 — the marketing site · progress report

Date: 2026-07-26 · Branch: `phase/6-sections` · 498 tests pass · 0 lint errors

`site/`, a sibling Vite project to `frontend/` sharing `shared/tokens.css`, served at `/site`.
Full design rationale is in `site/README.md`; this is what happened building it.

---

## The design, and the argument for it

The brief rules out the current defaults **by name** — cream with a serif display and a terracotta
accent, near-black with one acid accent, the broadsheet grid of hairline rules — and asks instead
for the subject's own vocabulary: plate boundaries, isobars, shipping charts, seismographs.

The product is called **Rhumb**, and a rhumb line is a real navigational object: a course that
crosses every meridian at a constant angle. On the portolan charts of the 14th–16th centuries those
lines were drawn as a radiating net from compass roses across the sheet, and that net is the single
most recognisable thing about those charts.

So the signature element is that net, and the page spends its boldness there and nowhere else. Line
weight varies by wind order — eight principal winds heaviest, eight half-winds lighter, sixteen
quarter-winds lightest — because reproducing that hierarchy is the difference between a wind rose
and a bicycle wheel. It is inline SVG: a few hundred bytes of geometry, no second asset request.

The accent pair comes from real Admiralty chart printing rather than a palette generator. Magenta
`#e8368f` is the overprint colour on nautical charts — lights, beacons, traffic separation schemes,
the layer that carries *information* rather than seabed. Verdigris `#45b5a0` is oxidised copper:
marine instrument patina, and the shallow-water tint on the same charts.

**The pair does information work rather than decoration.** Magenta is what the system *claims*;
verdigris is what actually *happened*. That mapping holds everywhere — an affected asset tagged up
is verdigris and down is magenta, the calibration chart draws stated confidence in magenta against
observed outcome in verdigris, the walkthrough's open steps are magenta-ruled and the settled one
verdigris. A reader who never reads the legend still absorbs it.

Type is Instrument Serif for display (one weight, section heads only), Inter for body, IBM Plex
Mono for every figure, timestamp and source. Self-hosted, so first paint never waits on a font host
and no visitor's IP reaches one.

---

## Two dependencies deliberately not taken

**No GSAP + Lenis, and no Framer Motion.** The brief offers them and then, two paragraphs later,
sets a first-contentful-paint target of 1.5 seconds. The smallest of those libraries is heavier than
this page's entire JavaScript. Scroll reveals are `IntersectionObserver` plus a CSS transition —
about twenty lines. Reduced motion is handled once in `shared/tokens.css` by collapsing the
duration rather than disabling the animation, so an element is never stranded invisible at frame
zero of an entrance it never plays.

**No `react-globe.gl`.** The brief asks for "an interactive globe where a visitor picks their
country"; the app already owns one, and it is 1.9MB lazy-loaded behind a WebGL check. The picker
here is an SVG equirectangular plate instead — and it is the more honest object, because exactly
ten countries have hand-checked exposure figures behind them and a globe you can spin implies you
can pick any of them.

---

## What building it found

### The personalisation promise was not working — at all

The demo is the brief's own feature: *pick your country and watch the same afternoon reorder
itself.* The first working version returned **the same three items in the same order for the UAE,
Brazil and Japan**, differing only in the third decimal of the score.

The cause is the mistake `CLAUDE.md` already calls the single most repeated one in this project:
**`geo` on an event is where the OUTLET sits, not what the story is about.** `geography.py` exists
specifically to solve it, and the globe and Exposure both honour it — but `relevance.score` did
not. Personal relevance was ranking on the publisher's country, which for a feed of largely US
financial media meant every reader in the world got the American ordering.

That is a headline feature of the product that has been silently broken since Phase 3, and nothing
surfaced it until a page whose entire job is to *demonstrate* it was pointed at real data.

Fixed at the root: `relevance.places()` derives the countries from what a claim affects, falling
back to the outlet's `geo` only when nothing maps, so no caller has to remember the rule. After the
fix the UAE leads with the Gulf and Gaza, Brazil with North Sea oil, Japan with a different set
again and different stated reasons. Three tests hold it, including one asserting the same claim
ranks higher for a Gulf reader than a Brazilian one.

### The data decided the walkthrough's shape

The brief asks for "what happened, the mechanism, the assets called, **what followed**". Every one
of the 323 resolved outcomes in the store belongs to a convergence signal; the event-derived claims
were all made recently and their horizons have not elapsed. There is no news event with a finished
outcome to walk.

Rather than reach for the signal-plane claim and present it as a news story, the walk ends where
the data actually ends: *"Not written yet. This call is open, and it gets marked on 30 July —
4 days from now — against the asset's excess return versus SPY, whichever way it goes."* A second
card alongside carries a genuinely finished call, drawn newest-first, which on the day this was
built was **GOSS up at 45% confidence → −3.4% against SPY → recorded a miss**.

That is a better section than the one originally specified. The step nobody else shows you is the
one that can go badly, and showing a countdown to being marked proves the loop exists more
convincingly than a hand-picked success would.

### GDELT came back

`docs/state.md` carried "GDELT has never been observed ingesting" as an open unknown for three
phases. It is ingesting — 4 events since 2026-07-25, and gdelt-sourced interpretations now appear
on the Radar and in the site's hero. The backoff simply elapsed. Small volume; worth watching
rather than assuming.

---

## The public boundary

Four unauthenticated GET endpoints back the page, behind one module (`tradeos/public_site.py`)
rather than more routes in `app.py`, so "what can a stranger see?" is answerable by reading one
file. Two rules hold there, both asserted mechanically in `tests/test_public_site.py` rather than
by inspection:

- **Nothing user-scoped.** No session parameter, no read of `users`, `trades`, `watchlists`,
  `user_profiles` or `trade_context`. The country preview personalises without a person — it takes
  an ISO code and scores against published reference data.
- **Nothing may be cherry-picked.** The walkthrough rotates by `date.toordinal() % len(pool)` over
  a pool ordered by recency alone, and the settled example is drawn newest-first with no verdict
  filter. A test asserts the selection statement is exactly that expression, because a marketing
  page that quietly picked its best day would make the Ledger a lie by omission.

---

## Measured

FCP 24ms, 296KB total transfer, app JS 7.5KB gzipped (vendor 45KB) on localhost. No console errors
on the site or on any of the eleven app surfaces re-checked after the relevance change. No
horizontal overflow at 390px. `FAQPage` and `SoftwareApplication` structured data are generated
from the same array the accordion renders, so the markup cannot drift from the visible answer.

Every section renders loading, empty and unreachable as three different sentences, and there is no
fixture data or placeholder copy anywhere on the page.

---

## Not done

**Where it is served in production.** The site is mounted at `/site` on the app's origin, which
makes both verifiable locally. It belongs on the apex domain with the app on a subdomain — that is
Phase 8's call, along with the signup handoff the CTAs currently point at.

**Lighthouse has not been run.** The measurements above are from the browser's own performance API
against localhost. The numbers are comfortable enough that the 90+ target looks safe, but that is
an inference, not a score.

---

**Status: Phase 7 complete.** Phase 8 (accounts, limits, deployment) is next.
