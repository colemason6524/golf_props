# Repository Instructions

Before changing code or generated research artifacts:

1. Run `git status --short --branch`.
2. Read `docs/project_handoff.md` completely. It is the authoritative current
   state, decision log, scientific guardrail, and next-task document.
3. Read `docs/research_narrative.md` for the story of learnings, successes,
   failures, current theory, and outward risks.
4. Read `README.md` and the documentation linked from the handoff when the task
   touches that area.
5. Run `PYTHONPATH=src python3 -m pytest` before substantive changes.

This repository currently has no commits. Most project files are untracked, and
large research data under `data/` is intentionally ignored. Do not delete,
reset, clean, or overwrite files merely because Git reports an unusual state.

Research rules:

- Preserve raw source data before normalization when collection is involved.
- Enforce point-in-time eligibility: only information available before the
  prediction timestamp may enter a feature.
- Keep sportsbook prices outside the performance model; use them only in the
  comparison/value layer.
- Treat the frozen 365-day/8-round/20-round-variance simulator as the incumbent
  until a challenger beats it under the documented paired rolling protocol.
- Do not call previously inspected events a prospective holdout.
- Do not claim a betting edge from structural-baseline performance tests or the
  legacy exploratory Bovada value report.
- Do not describe progress as literally “halfway”; phases are unequal. The
  binding gap is prospective evidence.
- Do not apply an ordinary top-65 cut assumption to no-cut playoff events
  without an explicit, logged event-structure decision.

The course identity crosswalk and frozen current-event workflow are complete.
The simulator now supports explicit `no_cut` event-structure handling and a
pre-start timestamp guard; frozen 365/8/20 strength is unchanged. Wyndham 2026
is retrospective only. The exact next queued task is the first genuinely
prospective frozen forecast for the 2026 TOUR Championship (competitive rounds
2026-08-27 to 2026-08-30; official field final after BMW concludes on
2026-08-23), described in `docs/project_handoff.md`. No background process or
partially completed code edit is active as of the 2026-08-20 handoff refresh.
