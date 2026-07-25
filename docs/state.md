# docs/state.md — where the work stands

Updated: 2026-07-25, end of Phase 0.
Read this after `CLAUDE.md` and before `docs/plan.md` at the start of every session.

---

## Current phase

**Phase 0 (audit) — complete, awaiting approval.** No feature code written, as specified.

Branch: `game-changer` (Phase 0 is documentation only; feature branches start at Phase 1 with
`phase/1-repair`).

---

## Finished

- Full read of the repository: 196 tracked files, 24,156 lines, 95 Python modules, 21 JSX,
  23 migrations, 98 API routes, 48 database tables.
- Live probing of the running stack (api + postgres + worker on Docker compose).
- Authenticated click-through of all twelve surfaces at 1440×900 in a headless browser.
  Zero console errors on every surface; screenshots captured.
- Direct execution of the vision, LLM, Reddit and scheduler paths inside the container.
- Deliverables written: `CLAUDE.md`, `docs/audit.md`, `docs/bugs.md`, `docs/dead_code.md`,
  `docs/plan.md`, this file, `docs/progress/phase_0.md`.

## Half finished

Nothing. Phase 0 has no partial work.

## Next three tasks

1. Get the two blocking decisions from the owner: **LLM provider** and **display name**
   (`docs/plan.md` §"What I need from you").
2. Open `phase/1-repair`, plan mode, and switch the model provider — this is time-critical
   (five days).
3. Fix the journal vision guard (B-01) with a real fixture-image test.

## Open questions waiting on the owner

| # | Question | Blocks |
|---|---|---|
| 1 | Switch `EXPLAIN_PROVIDER` to `gemini`? Add an OpenRouter fallback key? | Phase 3, and every AI surface after 2026-07-30 |
| 2 | Display name — proceed on `Rhumb`? | Phase 1 (one config value) |
| 3 | Reddit / OpenRouter / OpenFIGI free keys | Phase 1, Phase 2 |
| 4 | Six ASK rulings in `docs/dead_code.md` | Phase 1 cleanup |
| 5 | Confirm Portfolio may become Exposure | Phase 6 |

---

## Things learned that are not obvious from the code

Recorded because they cost time to discover:

1. **The reported "AI never sees my screenshot" bug is not a transport bug.** The model
   receives the image and reads it correctly; `directive_guard` rejects the phrase
   `target price` — which the prompt itself asks the model to discuss — and `_guarded`
   discards the entire analysis on one field's failure. The fallback then reports "no vision
   model connected", which is false. Full trace in `docs/bugs.md` B-01.

2. **GitHub Models is retired 2026-07-30.** The response headers say so
   (`Sunset: Thu, 30 Jul 2026`). It is the only configured provider. Five days of runway.

3. **`gemini-flash-latest` works on the existing key; `gemini-2.0-flash` is over quota and
   `gemini-2.5-flash` returns 404.** Gemini quota is per-model, so the model id is load
   bearing, not cosmetic.

4. **`make test` and the README's test command both fail** — `tests/` is deliberately not
   copied into the image. Mounting it works: 189 tests, 0.43s.

5. **Frontend changes need a full Docker rebuild.** The bundle is baked in at image build
   time. This is the biggest drag on the development loop and Phase 1 fixes it.

6. **The Social board's top names (BALL, POOL, DOV, FIX) are common English words**, not
   companies with unusual attention. Wikipedia pageview attribution has no disambiguation
   check.

7. **The scheduler is genuinely good** and already satisfies most of the brief's Phase 2
   worker requirements, including restart-safe cursors via `job_runs`. Extend it; do not
   build a second worker.

8. **Portfolio is not worthless.** Hidden inside it is a live public track record of
   shadowing each conviction bucket against SPY, published including its unflattering
   numbers. That mechanism is an early Ledger and should be salvaged, not deleted with the
   surface.

9. **The app has no router at all.** Navigation is `useState`. This blocks more than the
   marketing site and should be fixed in Phase 1.

10. **All five brand names in the brief are taken** on .com/.io/.ai; two of them are parked on
    an aftermarket reseller. Alternatives and reasoning in `docs/plan.md`.

11. **`llm.py`'s quota cooldown is a module-global** — one background job's 429 silences the
    user's interactive request for two minutes with no visible explanation.

12. The data is real and substantial: 664,923 insider transactions, 51,099 stake events,
    24,982 institutional holdings, 149 live convergence clusters. Treat it as an asset when
    weighing any "rewrite vs extend" decision.
