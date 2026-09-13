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
