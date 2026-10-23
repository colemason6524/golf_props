# DERIVED — not the source of truth

`frozen_model_manifest.json` in this directory is a **derived by-product** of
the 2026-10-07 rolling recompute, kept as the reference manifest for that
recompute report.

- **What it is:** the manifest written by the recompute run
  (`created_at_utc` 2026-10-07T02:46:01Z, `prospective_holdout_after`
  2026-10-07, SHA-256
  `2614f0427520cfc8b0548b008a38ac4ac214ac06504017e89289b17923c94122`).
  Its selection parameters are identical to the live manifest (365-day
  half-life, 8-round prior, 20 variance-prior rounds, cut size 65); only
  `created_at_utc` and `prospective_holdout_after` differ.
- **Why it exists:** it timestamps the recompute that produced `report.md`,
  `fold_metrics.csv` and the rest of this directory. It is evidence for that
  run, not a newer freeze of the model.
- **Not truth:** no module under `src/` reads this file. It is not a model
  update, and nothing has been repointed at it.

## Source of truth

`data/interim/reports/rolling_round_simulation_validation/frozen_model_manifest.json`,
hard-coded at `pipelines/weekly_forecast.py:113-117` (`WeeklyPaths.manifest`).
Recorded in `docs/INTEGRITY_AUDIT_2026-10-22.md` §6.
