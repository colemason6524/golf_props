# NEXT CHECKIN — golf_props

Updated 2026-10-01. Read after `docs/project_handoff.md`.

## 1) Status

- The Mac is the durable workspace and bulk-data location.
- Azure `/home/azureuser/golf_props` runs the scheduler via user systemd
  timers: `sports-golf-forecast.timer` every two hours at minute 17
  America/Detroit; `sports-golf-bovada.timer` Mon/Wed/Thu 08:56.
- Repository: `main` == `origin/main`; the 2026-09-18 dirty tree plus the
  2026-10-01 fixes are committed and pushed. Azure was synced to origin.

### 2026-09-30/10-01 Bank of Utah rescue

- Found on return from hiatus: the Bank of Utah field sat in `forecast_ready`
  for days with no archive (tee-time fallback deadlock) and ALL 115 players
  unmatched ("Last, First" source names). The flawed midnight-Oct-1 guard was
  ~35 minutes from marking the event `deadline_missed`.
- Fixes deployed pre-start; the forecast archived at 2026-10-01T03:26Z,
  archive-verified, and the Discord board was published (`status: sent`).
- Identity after fix: 113 matched, 2 unmatched admitted
  (Boston Bracken, Kristoffer Ventura).
- Archive:
  `data/interim/reports/prospective_forecasts/bank_of_utah_championship_2026/`.

## 2) Next action (with WHEN)

1. On/after 2026-10-04: preserve the CBS final leaderboard under
   `data/raw/prospective_results/bank_of_utah_championship_2026/` and run
   `grade-forecast`. Do NOT retune 365/8/20 based on this single grade.
2. Pull the Azure archive back to the Mac (copy, non-destructive) so both
   hosts hold the record.
3. The loop auto-advances to the next eligible event afterward.

## 3) What to check on pop-back

- `weekly-forecast-status` on either host: after grading, the loop should be
  waiting/advancing; exit 0 quiet.
- Azure: `systemctl --user list-timers --all | grep sports-golf` and the newest
  `logs/weekly_forecast.log` entries.
- Copy-back integrity: `predictions.csv` SHA-256 must match between hosts.

## 4) What NOT to do

- No retune from the Bank of Utah grade — two graded events is still thin
  evidence; frozen 365/8/20 incumbent stays.
- `make_cut` IS gradable for this event (ordinary top-65 cut), unlike the
  no-cut playoff events.
- Do not `git clean` generated research data.
- No model/odds changes based on one more event; books remain a comparison
  layer only, post-freeze.

## 5) Leave-off pointer

- `docs/project_handoff.md` — "Exact Stopping Point" (2026-10-01 session block).
- Grade artifacts will live under
  `data/interim/reports/prospective_forecast_grades/bank_of_utah_championship_2026/`.

## 6) Small later ideas (pick at most one)

- Investigate why the collector's tee-time parser returned nothing this week
  (official site has tee times); exact tee times would restore T-12 scheduling.
- Add durable timestamped Bovada history without changing the frozen
  performance inputs.
- Add archive freshness and next-wait-reason telemetry to status output.
