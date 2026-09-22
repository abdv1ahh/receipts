# docs/archive

Long-form documents that were written during a particular piece of work and are kept for the record
rather than for daily reading. They are **tracked, not deleted** — each one is the reasoning behind a
decision that is now load-bearing somewhere in the code, and a decision whose reasoning has been
thrown away is a decision nobody can revisit.

Nothing here is a current reference. `CLAUDE.md`, `docs/state.md` and `docs/plan.md` are. If a fact
in this directory disagrees with one of those three, those three win.

| File | Written | What it is |
|---|---|---|
| `TRADEOS_AUDIT.md` | 2026-08-21 | A forensic read of the whole repository, 3,043 lines. **Its own opening records that the Docker daemon was down when it was written, so no row count in it was verified** — every figure is quoted from the project's written record, not measured. Treat its numbers as claims, not measurements. |
| `EXPOSURE_FEASIBILITY.md` | 2026-08-23 | "Can this codebase become an event-to-company-exposure engine?", measured against a running stack. Corrects three figures in its own brief — notably that the signal plane has **473 resolved claims**, not 412; 412 is the hit-or-miss count, and a further 61 resolved `inconclusive`. |
| `RECEIPTS_CLAUDE_CODE_PROMPT.md` | 2026-09-02 | The brief Receipts was built from. Useful for understanding *why* the design refuses things — the append-only trigger, the 25-call sample gate, the 2% noise floor — rather than how it works. For how it works, read `docs/analysis/receipts_explained.md`. |

Moved here from the repository root on 2026-09-13. Together they were 4,321 lines — 41% of the
`receipts` branch diff, none of it code — and they made the root listing hard to read.

---

## Superseded by the Receipts extraction (2026-09-23)

Six more documents moved here when sections A, B and C of `docs/release_plan.md` were executed and
68 modules, 113 routes and the whole research plane were deleted. **They are accurate about the
system they describe. That system is at the tag `research_platform`, not on `main`.**

| file | what it was |
|---|---|
| `state.md` | "where the work stands" across ten phases of the research platform |
| `plan.md` | "where it is going" — the ten-phase plan, all of it delivered |
| `demo-script.md` | a walkthrough of surfaces that no longer exist |
| `review-queue.md` | the review queue for those phases |
| `TRADEOS_INVENTORY.md` | a full inventory of the pre-extraction system |
| `tradeoss_veryimportant_prompt.md` | the original product brief the ten phases were built against |

They were archived rather than deleted because they are the reasoning behind decisions the current
code still depends on, and because a deleted document cannot be checked against the tag that still
runs it. `docs/release_readiness.md` is where the work stands now; `CLAUDE.md` is the operating
manual.

Note that `TRADEOS_INVENTORY.md` is on `release_plan.md` §K.1's list of paths to remove from every
commit, so it will not survive the history rewrite. Archiving it is about what `main` claims today,
not about keeping it forever.
