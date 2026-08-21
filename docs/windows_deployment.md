# Windows Deployment

Last updated: 2026-08-21

How the golf_props repo is mirrored to the Windows Task Scheduler host, matching
the horses/tennis pattern.

## Layout

- Mac (source of truth): `/Users/colemason/Documents/golf_props`
- GitHub remote: `https://github.com/colemason6524/golf_props.git` (`origin`)
- Windows checkout: `C:\Users\muski\golf_props`
- Windows venv: `C:\Users\muski\golf_props\.venv`
- Windows user profile (via `ssh windows`): `C:\Users\muski` (the `windows` ssh
  alias in `~/.ssh/config` connects to the desktop that runs the horses
  scheduler; the session environment resolves `USERPROFILE` to `muski`).

## Current state

- Mac `main` has 5 commits pushed to `origin/main` (bootstrap scaffold, 2026-08-10
  decision docs, no-cut + pre-start guard, 2026-08-20 docs refresh, `logs/.gitkeep`).
- Windows clone is on `main` tracking `origin/main`; 117 tests pass on both hosts.
- Essential research data is mirrored to Windows so `predict-current-event` can
  run there with hash verification passing:
  - `data/processed/pga_2001_2026`
  - `data/interim/features/pga_2001_2026_round_performance.csv`
  - `data/interim/reports/rolling_round_simulation_validation/frozen_model_manifest.json`
  - `data/raw/fields`
  Verified identical hashes for the frozen manifest and round performance file.

## Commands

Refresh from origin on Windows:

```bat
cd /d C:\Users\muski\golf_props
git pull
```

Run tests on Windows:

```bat
cd /d C:\Users\muski\golf_props
.venv\Scripts\python -m pytest
```

Run the tests on the Mac:

```bash
cd /Users/colemason/Documents/golf_props
PYTHONPATH=src python3 -m pytest
```

## Task Scheduler tasks

| Task name | Wrapper | Purpose | Schedule |
|---|---|---|---|
| `GolfBovadaCollect` | `scripts/windows/run_bovada_collect.cmd` | Bovada PGA odds snapshot (research only) | Recurring Mon/Wed/Thu (currently 09:00) |
| `GolfTourChampionshipForecast` | `scripts/windows/run_tour_championship_forecast.cmd` | One-shot frozen no-cut prospective forecast | One-shot 2026-08-26 09:00 (before Thu tee) |

The forecast task is deliberately staged:

1. It exits 0 (skip) if
   `data\raw\fields\tour_championship_2026_field.csv` does not exist yet.
2. It exits 0 (skip) if the bundle
   `data\interim\reports\tour_championship_2026_frozen_simulation\run_manifest.json`
   is already archived.
3. It never overwrites an archived forecast.
4. `TOUR_START_UTC` in the `.cmd` is a placeholder that must be set to the
   verified first-tee UTC timestamp once tee times are posted (2026-08-25/26).

The official top-30 field is only final after BMW concludes on 2026-08-23.
Preserving that field is a manual/scripted step; the scheduled forecast only
executes when the preserved field exists.

## Pull-back routine

Generated artifacts (odds snapshots, forecast bundles, logs) accumulate on
Windows and are intentionally outside Git. Periodically mirror them back to the
Mac with `scp` or `rsync`, mirroring the horses `windows_pull_*` pattern:

```bash
mkdir -p /Users/colemason/Documents/golf_props/windows_pull_$(date +%F)
scp -r windows:"C:/Users/muski/golf_props/data/raw/odds_snapshots" /Users/colemason/Documents/golf_props/windows_pull_$(date +%F)/
scp -r windows:"C:/Users/muski/golf_props/data/processed/odds_snapshots" /Users/colemason/Documents/golf_props/windows_pull_$(date +%F)/
scp -r windows:"C:/Users/muski/golf_props/data/interim/reports/tour_championship_2026_frozen_simulation" /Users/colemason/Documents/golf_props/windows_pull_$(date +%F)/ 2>/dev/null || true
scp -r windows:"C:/Users/muski/golf_props/logs" /Users/colemason/Documents/golf_props/windows_pull_$(date +%F)/ 2>/dev/null || true
```

Do not stage or push generated data, odds snapshots, forecast bundles, or logs.

## Scientific guardrails (unchanged)

- The frozen 365/8/20 strength manifest is never modified on either host.
- Odds never enter the performance model; Bovada snapshots are a separate layer.
- The TOUR Championship bundle, once archived, is graded after the event without
  retuning. `make_cut` is structural (1.0) under `no_cut` and is not a target.
- A scheduled forecast cannot backfill: `predict-current-event` rejects any run
  whose creation time is not strictly before `--event-start-at-utc`.
