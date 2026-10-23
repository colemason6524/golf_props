# LEGACY — not the source of truth

`data/frozen_model_manifest.json` is a **legacy tracked copy** of the frozen
model manifest.

- **What it is:** a byte-identical copy (SHA-256
  `8ee96b9f6567b93ec0cb0d36f1477fa7d193124d96298d4cd914800f70a54291`) of the
  manifest the production loop loads: 365-day half-life, 8-round prior, 20
  variance-prior rounds, cut size 65, frozen 2026-08-06.
- **Why it exists:** the live manifest lives under `data/interim/`, which is
  gitignored, so a clone had no copy of the frozen parameters. This tracked
  copy was force-added so the configuration is inspectable from a clone.
- **Not truth:** no module under `src/` reads this file. Do not repoint code at
  it without changing the docs and
  `tests/test_frozen_manifest_source_of_truth.py`.

## Source of truth

`data/interim/reports/rolling_round_simulation_validation/frozen_model_manifest.json`,
hard-coded at `pipelines/weekly_forecast.py:113-117` (`WeeklyPaths.manifest`).
Recorded in `docs/INTEGRITY_AUDIT_2026-10-22.md` §6.

Never edit this JSON to change a model parameter: production reads the live
manifest, not this copy. If the two ever drift apart, that is a defect to
record, not a reason to repoint the code.
