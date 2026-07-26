# site/ — the Rhumb marketing site

A sibling Vite project to `frontend/`, sharing `shared/tokens.css`. Not an npm workspace: this is a
Python repository with two small front ends, and converting to workspaces to host one extra site is
more machinery than the problem needs (`docs/plan.md` §6).

```bash
cd site && npm install     # once
make site                  # build (~0.3s), served at http://localhost:8000/site/ under `make dev`
npm run dev                # or a standalone dev server on :5174, /api proxied to :8000
```

`site/dist/` and `tradeos/site_static/` are gitignored, exactly like the app's bundle.

## Where it is served

FastAPI mounts the built bundle at **`/site`**, registered before the app's catch-all `/` mount.
Both bundles therefore live on one origin, which is what makes the site verifiable locally against
real data. **Phase 8 moves it**: the site belongs on the apex domain and the app on a subdomain,
which is the split the brief implies by calling it "a separate public application".

## What it renders

Everything on the page is live from the store through four public, unauthenticated, GET-only
endpoints — `/api/public/live`, `/api/public/walkthrough`, `/api/public/frame` and `/api/ledger`.
There is **no fixture data and no placeholder copy anywhere**, which is the same rule the app
holds. Each section renders loading, empty and unreachable as three different sentences.

The boundary those endpoints sit behind is `tradeos/public_site.py`; its docstring states the two
rules, and `tests/test_public_site.py` asserts them mechanically rather than by inspection.

## The design, and why it is this

The brief rules out the current defaults by name — cream with a serif display and a terracotta
accent, near-black with one acid accent, the broadsheet grid of hairline rules — and asks for the
subject's own vocabulary, which is cartographic and instrumental.

**The signature element is the rhumb-line net** (`src/rose.jsx`): a 32-point portolan wind rose
whose lines run off every edge of the hero. A rhumb line is a real navigational object — a course
crossing every meridian at a constant angle — and it is what the product is named after. Line
weight varies by wind order (principal, half, quarter) because that hierarchy is what separates a
wind rose from a bicycle wheel. Everything else on the page is deliberately quiet; the brief is
right that boldness spent in more than one place is just noise.

**The accent pair is taken from Admiralty chart printing**, not from a palette generator:

| | | |
|---|---|---|
| magenta | `#e8368f` | the overprint colour on nautical charts — lights, beacons, traffic schemes |
| verdigris | `#45b5a0` | oxidised copper: marine instrument patina, and the shallow-water tint |

They are used at opposite ends of one idea — **magenta for what the system claims, verdigris for
what actually happened** — and that mapping holds everywhere on the page, so the colour carries
information rather than decorating. The field is deep ocean ink with a green undertone; text is
warm chart buff, never pure white.

**Type**: Instrument Serif for display (one weight, used only at section heads), Inter for body,
IBM Plex Mono for every figure, timestamp and source. All three self-hosted via fontsource — no
external font request, so first paint never waits on a third party and no visitor's IP reaches one.

## Dependencies, and the ones deliberately not taken

React and three font packages. That is the whole list.

- **No GSAP + Lenis, no Framer Motion.** The brief offers them; a marketing page whose first paint
  waits on an animation library fails the performance target set two paragraphs later in the same
  brief. Scroll reveals are `IntersectionObserver` plus a CSS transition — about twenty lines in
  `src/hooks.js`. Reduced motion is handled once in `shared/tokens.css`, by collapsing the
  duration rather than disabling the animation, so an element is never stranded invisible at frame
  zero.
- **No `react-globe.gl`.** The app's globe is 1.9MB and lazy-loaded behind a WebGL check. The
  country picker here is an SVG equirectangular plate (`src/worldmap.jsx`) — a few hundred bytes,
  and the more honest object: exactly ten countries have hand-checked exposure figures, and a globe
  you can spin implies you can pick any of them.

## Measured

FCP 24ms and 296KB total transfer on localhost; app JS 7.5KB gzipped, vendor 45KB. No console
errors, no horizontal overflow at 390px. `FAQPage` and `SoftwareApplication` structured data are
generated from the same array the accordion renders, so the markup cannot drift from the visible
answer.
