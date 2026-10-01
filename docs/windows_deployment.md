# Retired Windows Deployment

Last updated: 2026-09-16

> **Retired 2026-09-08.** Do not restore, modify, or depend on this host or its
> Task Scheduler tasks. It is retained only as historical documentation for the
> 2026 TOUR Championship archive-of-record. Current operations are documented in
> `docs/azure_deployment.md`; the Mac is the durable workspace and bulk-data
> location.

## Historical Layout

- Mac (source of truth): `/Users/colemason/Documents/golf_props`
- GitHub remote: `https://github.com/colemason6524/golf_props.git` (`origin`)
- Windows checkout: `C:\Users\muski\golf_props`
- Windows venv: `C:\Users\muski\golf_props\.venv`
- Windows user profile (via `ssh windows`): `C:\Users\muski` (the `windows` ssh
  alias in `~/.ssh/config` connects to the desktop that runs the horses
  scheduler; the session environment resolves `USERPROFILE` to `muski`).

## Current state

- At retirement, the Windows clone was no longer an active deployment target.
  Current code and documentation history is maintained on Mac `main`; Azure is
  the only active scheduler host.
- Windows is retained only as historical context for the TOUR Championship
  archive-of-record and is not part of current validation.
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
| `GolfWeeklyForecast` | `scripts/windows/run_weekly_forecast.cmd` | Generic weekly frozen forecast (discovery, evidence, identity, archive) | Recurring every 2 hours |
| `GolfBovadaCollect` | `scripts/windows/run_bovada_collect.cmd` | Bovada PGA odds snapshot (research only) | Recurring Mon/Wed/Thu (currently 09:00) |

The one-shot `GolfTourChampionshipForecast` fallback was retired on 2026-08-25
once the generic weekly task was armed with the official final field; its
hardcoded placeholder tee timestamp made it unsafe as a fallback, and its
wrapper remains only in Git history.

### Generic weekly task (`GolfWeeklyForecast`)

`scripts/windows/run_weekly_forecast.cmd` runs `python -m golf_props.cli
weekly-forecast`, which is idempotent and fail-closed:

1. Discovers the next main PGA Tour event from the preserved CBS schedule
   (raw schedule is saved with a provenance manifest; CBS is discovery only and
   never supplies timing or structure).
2. Waits for reviewed **official** final field evidence (a sportsbook source can
   only be a cross-check diagnostic).
3. Waits for reviewed tee-time evidence and derives the earliest Round 1 tee in
   UTC (local timezone required); the forecast is scheduled for T-12 hours.
4. Resolves player identities against the canonical roster plus
   `config/player_aliases.csv`; ambiguous/unknown/unmatched names block.
5. Runs the frozen 365/8/20 forecast into a staging directory, copies all
   evidence, writes an `archive_manifest.json` hash index, and atomically
   promotes the bundle to `data/interim/reports/prospective_forecasts/<event_key>/`.
6. Never overwrites an archived forecast and never backfills after the verified
   first tee (`predict-current-event` rejects both).

Exit codes recorded by Task Scheduler:

| Code | Meaning |
|---|---:|
| 0 | Waiting (evidence not ready / not yet due) or already archived |
| 10 | Blocked (no reviewed next event, unreviewed structure, frozen refusal) |
| 11 | Deadline missed (first tee passed without an archive) |
| 12 | Identity blocked (unresolved field identities) |
| 20 | Hard error (schedule/source/archive failure) |

Reviewed configuration files (authoritative, operator-maintained):

- `config/event_registry.csv` — scope (include/exclude) and event-structure
  decisions per season. An event with no reviewed row is never selected.
- `config/player_aliases.csv` — reviewed source-variant to canonical player IDs.

Operational commands:

```bat
cd /d C:\Users\muski\golf_props
.venv\Scripts\python -m golf_props.cli weekly-forecast              rem run the loop
.venv\Scripts\python -m golf_props.cli weekly-forecast --dry-run   rem never archives
.venv\Scripts\python -m golf_props.cli weekly-forecast-status      rem print status.json
.venv\Scripts\python -m golf_props.cli verify-forecast-archive --archive-dir data\interim\reports\prospective_forecasts\<event_key>
.venv\Scripts\python -m golf_props.cli import-current-field-evidence --event-key <key> --event-name <name> --payload <file.csv> --org official --url <url> --captured-at-utc <iso> --finality final
.venv\Scripts\python -m golf_props.cli import-current-tee-time-evidence --event-key <key> --event-name <name> --payload <file.csv> --org official --url <url> --captured-at-utc <iso> --local-timezone <IANA> --reviewed-by operator
```

Status and control files live under `data/interim/weekly/`:
`status.json`, `current_event_key.txt`, `<event_key>/event_control.json`,
`<event_key>/identity_audit.json`.

The official top-30 field was preserved on 2026-08-25 (PGA TOUR field page,
official final, 30 rows, all identities resolve); both hosts are in
`awaiting_tee_times` until reviewed Round 1 tee-time evidence is imported.

## Pull-back routine

Generated artifacts (odds snapshots, forecast bundles, weekly state, logs)
accumulate on Windows and are intentionally outside Git. Periodically mirror
them back to the Mac with `scp` or `rsync`, mirroring the horses
`windows_pull_*` pattern:

```bash
mkdir -p /Users/colemason/Documents/golf_props/windows_pull_$(date +%F)
scp -r windows:"C:/Users/muski/golf_props/data/raw/odds_snapshots" /Users/colemason/Documents/golf_props/windows_pull_$(date +%F)/
scp -r windows:"C:/Users/muski/golf_props/data/processed/odds_snapshots" /Users/colemason/Documents/golf_props/windows_pull_$(date +%F)/
scp -r windows:"C:/Users/muski/golf_props/data/interim/reports/prospective_forecasts" /Users/colemason/Documents/golf_props/windows_pull_$(date +%F)/ 2>/dev/null || true
scp -r windows:"C:/Users/muski/golf_props/data/interim/weekly" /Users/colemason/Documents/golf_props/windows_pull_$(date +%F)/ 2>/dev/null || true
scp -r windows:"C:/Users/muski/golf_props/data/raw/current_events" /Users/colemason/Documents/golf_props/windows_pull_$(date +%F)/ 2>/dev/null || true
scp -r windows:"C:/Users/muski/golf_props/logs" /Users/colemason/Documents/golf_props/windows_pull_$(date +%F)/ 2>/dev/null || true
```

Do not stage or push generated data, odds snapshots, forecast bundles, logs, or
weekly state.

## Scientific guardrails (unchanged)

- The frozen 365/8/20 strength manifest is never modified on either host.
- Odds never enter the performance model; Bovada snapshots are a cross-check
  layer only and can never authorize the performance-model field of record.
- A forecast bundle, once archived, is graded after the event without retuning.
  `make_cut` is structural (1.0) under `no_cut` and is not a target.
- A scheduled forecast cannot backfill: `predict-current-event` rejects any run
  whose creation time or completion time is not strictly before
  `--event-start-at-utc`, and refuses to overwrite an existing bundle.
- Event timing and structure come only from reviewed evidence, never from the
  CBS schedule or sportsbook markets.
