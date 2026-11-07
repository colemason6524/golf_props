> History. Current state is this sport’s VM `.dashboard/checkpoint.json`. This file is not the live schedule.

# NEXT CHECKIN — golf_props

Updated 2026-11-05. Read after `docs/project_handoff.md`.

## 1) Status

- Azure `/home/azureuser/golf_props` is the active scheduler; both
  `sports-golf-forecast.timer` and `sports-golf-bovada.timer` are active.
- The 2026 WWT forecast archive verifies and its board was sent. Both preserved
  Bovada captures now price the board through the corroborated
  `WWT Championship -> World Wide Technology Championship` initialism join.
- The reviewed identity/price/freshness/refresh code delta is deployed. Live
  and staged suites: **398 passed** on both Mac and Azure Python 3.10.
- Active performance inputs were refreshed and activated on both hosts on
  2026-11-05: canonical `data/processed/pga_2001_2026_20261104/`, round
  performance `..._20261104_round_performance.csv`, live manifest SHA-256
  `bb414ca1…`. Frozen parameters remain 365/8/20; `source_data_through` is
  `2026-10-31`; `prospective_holdout_after` is `2026-11-05`.
- Freshness now reports `stale` with exactly one missing event, The Open
  Championship; `missing_immediately_preceding=false`. The Open is blocked on
  authoritative finality evidence. Presidents Cup is excluded as team match
  play.
- The scheduler is at `austin_championship_2026` / `awaiting_field`; official
  start 2026-11-12. A dry-run weekly pass exited 0 and wrote the new freshness
  state.

## 2) Next action (with WHEN)

Activation is complete. Do not repeat it.

1. Let the scheduled loop advance Austin when its official field appears.
2. Before/at the Austin forecast, verify `weekly-forecast-status` and
   `health.json` show the activated cutoff `2026-10-31` and Austin remains
   `awaiting_field`/`forecast_ready` as expected.
3. At publication, confirm the board shows the refreshed history status
   (only The Open missing) and real price coverage/readiness.
4. After Austin completes, grade and recap normally; do not retune from one event.

The Open remains missing until an authoritative final result page passes
`analyze_leaderboard_finality`; do not bypass the strict gate.

## 3) What to check on pop-back

- `weekly-forecast-status`: Austin state, field readiness, and
  `history_freshness`.
- `data/interim/weekly/health.json`: `history_freshness.status`,
  `missing_events`, `candidate_refresh`.
- Austin archive/board: `data through` must equal `2026-10-31`; the board must
  include a History status field (only The Open missing).
- Prices: board `odds.readiness`; if unpriced, inspect
  `event_identity_diagnostics` and `observed_provider_events` before assuming a
  collection failure.
- If markets appear after publication, use `price-addendum` dry-run first.

## 4) What NOT to do

- Do not rewrite the WWT archive or reuse it as refreshed-input evidence.
- Do not delete or overwrite `data/processed/pga_2001_2026` or the July-11
  round-performance file; they are the rollback. The pre-activation manifest is
  `frozen_model_manifest_pre_20261104.json`.
- Do not retune 365/8/20 from the refreshed-input diagnostic or one event.
- Do not bypass the finality gate for The Open.
- Do not `git clean` ignored research data.

## 5) Leave-off pointer

- `docs/project_handoff.md` — “2026-11-04/05 session” under Exact Stopping Point.
- Activated inputs: `data/processed/pga_2001_2026_20261104/` and
  `data/interim/features/pga_2001_2026_20261104_round_performance.csv`.
- Diagnostic: `data/interim/reports/history_refresh/20261104/diagnostic/comparison.json`.
- Price verification:
  `data/interim/reports/prospective_price_verification/world_wide_technology_championship_2026/`.
- Deployment backup on Azure:
  `/home/azureuser/.cache/hermes-backups/golf-step8-20261105T002402Z/`;
  activation backup:
  `/home/azureuser/.cache/hermes-backups/golf-activation-20261105T003248Z/`.
