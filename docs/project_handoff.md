# Golf Props Project Handoff

Last updated: 2026-08-28

This is the authoritative continuity document for the repository. A new agent
should read this file before making changes. It records the project goal,
current implementation, verified evidence, rejected ideas, data/source state,
scientific constraints, exact stopping point, and next task.

For the story of successes, failures, current theory, and outward risks, also
read `docs/research_narrative.md`. For a copy-ready new-session prompt, use
`docs/continuation_prompt.md`.

## Executive State

The repository is a PGA golf performance and sportsbook-value research
prototype inspired by Bill Benter-style data discipline. Its core objective is
not merely to pick winners. It is to produce point-in-time-safe player outcome
probabilities, eventually compare them with archived sportsbook prices, and
identify whether prices are miscalibrated.

The performance model does not require odds as an input. Odds are a separate,
perishable comparison layer. This decision allows the performance intelligence
to improve even while sportsbook access remains inconsistent.

**Progress framing:** do not call the project literally “halfway done.” Roadmap
phases are unequal. We are advanced on the performance-model foundation and
still early on prospective validation and market-edge research. The binding gap
is prospective evidence, not additional model complexity and not sportsbook
access.

The current performance incumbent is a field-level round-strength tournament
simulator with:

- event-round-relative score as the public-data performance proxy
- 365-day exponential half-life
- 8-round mean shrinkage prior
- 20-round variance shrinkage prior
- seeded joint-field tournament simulation
- top-65-and-ties cut after two rounds
- make-cut, top-20, top-10, top-5, and winner probabilities

Four rolling annual folds selected the same incumbent parameters and beat a
simple field-structure baseline. The model is promising as a performance
engine, but this is not evidence of a betting edge.

A reviewed cross-source course identity crosswalk now links CBS 2026 venues to
historical ESPN course IDs. Latest-window same-course player coverage rose from
0% to 62.9886%. The paired same-course residual challenger was rerun but still
did not earn promotion; the incumbent remains unchanged. Phase 6 is therefore
partially started: identity repair and a rejected residual challenger exist;
richer course profiles, strokes-gained enrichment, and true course-fit modeling
have not started.

The frozen incumbent is operational through `predict-current-event`. The
command verifies manifest input hashes, locks 365/8/20 parameters, enforces
point-in-time and prospective eligibility, and writes a reproducible
performance-only forecast bundle.

The simulator now supports an explicit `no_cut` event-structure rule alongside
the ordinary `top_n_and_ties` cut. Prospective runs additionally require a
timezone-aware `--event-start-at-utc` timestamp that is strictly after the run's
creation time, so a forecast cannot be backfilled after tee time. This is a
structural adaptation; the frozen 365/8/20 strength parameters are unchanged.
`make_cut_prob` is deterministic (1.0) under `no_cut` and is not an empirical
target for such events.

## Exact Stopping Point

No command or background process is currently running. Documentation was
refreshed on 2026-08-28.

**The first genuinely prospective frozen forecast was archived before the first
tee and is the project's primary prospective artifact:**

- the Windows-scheduled `GolfWeeklyForecast` task archived the 2026 TOUR
  Championship bundle at 2026-08-27T04:00:02Z (12:00 AM EDT Thursday), about
  11 hours before the verified 2026-08-27T15:00:00Z first tee;
- `pre_start_verified=true`; `verify-forecast-archive` passes on both hosts;
- the bundle was pulled back to the Mac and its `predictions.csv` SHA-256
  (`412f99b501d33d769c12d1f4d257405a7177d55d0925d1daaa1d72e034276fcb`) matches
  the Windows record byte-for-byte;
- archive location (both hosts):
  `data/interim/reports/prospective_forecasts/tour_championship_2026/`;
- the Mac's local weekly state for this event reads `deadline_missed` because
  its loop ran after the tee passed; that is a local state artifact only. The
  Windows archived bundle is the record (per the archive-of-record decision).

**Next event review completed 2026-08-28:** the loop had been exiting 10
(`blocked`) every two hours since the archive because the next CBS-discovered
event, `Biltmore Championship Asheville`, had no reviewed registry row. That is
designed fail-closed behavior, not a bug. It was resolved by an official-source
review and a new registry row:

- official source (preserved under
  `data/raw/current_events/_registry_review/`): PGA TOUR schedule page,
  tournament id `R2026557`, name `Biltmore Championship Asheville`,
  The Cliffs at Walnut Cove, Asheville, NC;
- official dates **2026-09-17 to 2026-09-20** (the CBS discovery schedule says
  Sep 16-19; CBS is discovery-only and the official page is authoritative for
  timing);
- FedExCup Fall points event (500 pts, $5M purse): a main-field event, not
  opposite-field;
- structure decision (explicit and logged): 72-hole stroke play, 4 rounds,
  ordinary `top_n_and_ties` cut with the frozen cut size 65;
- inclusion decision: `include=1` **provisionally** under the operator rule
  "include when book markets exist." Bovada had not yet posted Biltmore
  markets as of 2026-08-27 (feed listed only TOUR Championship). Re-check
  Bovada market availability before 2026-09-10; if markets never appear, flip
  `include` to 0 so the loop skips ahead.

Both hosts now select the Biltmore Championship Asheville and wait quietly in
`awaiting_field` (exit 0) until reviewed official field evidence is imported.

Preserve that forecast bundle unchanged for later grading. Keep sportsbook
prices outside the performance computation, and do not use a retrospective
replay as prospective evidence. Do not modify the frozen strength parameters
(365/8/20) while addressing event structure.

## Git and Workspace State

As of 2026-08-21 the repository has its first commits pushed to a remote:

```text
origin  https://github.com/colemason6524/golf_props.git (fetch/push)
main    origin/main  (9 commits, no force pushes)
```

Commits in order:

1. `Bootstrap runnable PGA golf props research scaffold`
2. `Document course identity crosswalk and frozen incumbent decision log (2026-08-10)`
3. `Add explicit no-cut event-structure support and pre-start timestamp guard`
4. `Refresh docs for 2026-08-20 handoff (no-cut support, TOUR Championship next eligible)`
5. `Track logs directory scaffold so fresh clones pass scaffold checks`
6. `Add Windows Task Scheduler deployment (Bovada collect + staged TOUR Championship forecast)`
7. `Ignore generated task logs on Windows`
8. `Ignore editable-install egg-info artifacts`
9. `Add weekly frozen forecast automation (discovery, evidence, identity, archive)`

The repo is mirrored to the Windows Task Scheduler host at
`C:\Users\muski\golf_props` (see `docs/windows_deployment.md`). Windows runs
the same test suite and has the frozen manifest, canonical history, and
round-performance features with verified identical hashes. A generic recurring
`GolfWeeklyForecast` task runs every two hours; the one-shot TOUR Championship
fallback task was retired on 2026-08-25 (placeholder tee timestamp, superseded
by the generic loop).

Large generated/research data under `data/raw`, `data/processed`, and
`data/interim` is intentionally ignored by `.gitignore`, but it is essential
local research state and is mirrored between hosts (Mac -> Windows for model
inputs, Windows -> Mac via the pull-back routine for generated artifacts). Do
not `git clean`, reset, delete, or revert files.

The latest verified test result at handoff refresh:

```text
167 passed
```

## Project Principles and Non-Negotiable Rules

1. Raw-source-first collection. Save source payloads/pages before parsing when
   feasible.
2. Canonical tables before modeling. Source-local names and IDs must not leak
   into downstream assumptions without explicit normalization.
3. Strict point-in-time features. For a tournament starting at `T`, only events
   completed before `T` may enter pre-tournament strength.
4. Prices are not performance features. Sportsbook data belongs in the final
   market-comparison layer.
5. Use chronological validation. Never randomly split player-event rows.
6. Resample tournaments, not player rows, for uncertainty because golfers in
   the same field are dependent.
7. Freeze before prospective evaluation. An event is genuinely prospective
   only if it starts after both the source-data cutoff and model-freeze date.
8. Keep a zero-effect challenger candidate. New feature families must be able
   to lose honestly.
9. Do not claim an edge without stable archived prices and enough truly
   out-of-sample events.
10. Preserve the incumbent when a challenger fails.
11. Do not retune frozen strength parameters to chase a single upcoming event.
12. Encode true event structure explicitly; do not silently apply a full-field
    cut model to no-cut playoff events.

## Scope and Assumptions

- PGA Tour first.
- Pre-tournament modeling is the active scope.
- Ordinary 72-hole stroke play with a top-65-and-ties cut is the simulator's
  current structural assumption.
- FedExCup Playoffs events (St. Jude, BMW, TOUR Championship) currently violate
  that assumption via no-cut and/or special formats.
- Live tournament state, in-progress rounds, tee-wave adjustments, weather,
  withdrawal risk, multi-course routing, and nonstandard formats are future
  work.
- Public event-round-relative scoring is a proxy, not official ShotLink
  strokes gained.
- Research only. There is no betting execution or bankroll automation.
- Manual odds normalization exists for fixtures/fallback only; automated
  collection is the intended workflow.

## Current Data Inventory

Canonical input directory:

```text
data/processed/pga_2001_2026
```

Verified audit:

| Item | Value |
|---|---:|
| Event date range | 2001-01-11 to 2026-07-08 |
| Events | 1,172 |
| Events with results | 1,171 |
| Courses | 180 |
| Reviewed course-alias rows | 32 |
| Event-course rows | 1,172 |
| Players | 4,332 |
| Player-event results | 152,357 |
| Derived player-event feature rows | 152,357 |
| Raw canonical round scores | 467,881 |
| Derived usable round-performance rows | 467,787 |
| Event-round groups | 4,653 |
| Players with derived rounds | 4,297 |
| Out-of-range rounds excluded | 94 |

The only event without results in the audit is The Sentry starting 2026-01-07.
Derived valid 18-hole scores range from 58 to 94. The builder's accepted range
is 58–110.

Important cutoff distinction:

- latest canonical event start in the audit: 2026-07-08
- latest completion consumed by the frozen model: 2026-07-11
- model freeze date: 2026-08-06 UTC
- earliest valid prospective holdout must start after 2026-08-06

Events already played before the freeze date cannot be labeled prospective
merely because their rows are not yet in the local dataset.

## Architecture and Data Flow

Historical performance path:

```text
raw/downloaded results
  -> source-specific normalizers
  -> canonical events/courses/players/results/round_scores
  -> merged canonical directory
  -> event-round-relative performance
  -> point-in-time player strength
  -> joint-field tournament simulation
  -> chronological validation/calibration
```

Current tournament performance path:

```text
independent field CSV
  + frozen incumbent manifest
  -> hash and eligibility verification
  -> point-in-time 365/8/20 round strength
  -> seeded joint-field tournament simulation
  -> hashed performance-only forecast bundle
```

Odds path:

```text
Bovada public JSON service
  -> raw JSON snapshot
  -> canonical odds snapshot CSV
  -> market join/value report
```

The current odds/value path is not yet wired to the validated frozen simulator.
The existing `current-event-rankings` command uses older rolling-rate and event-
history heuristics. Odds integration remains a later comparison layer and must
not block prospective performance validation.

## Implementation Map

### Ingestion and normalization

- `src/golf_props/ingestion/cbs_results.py`: CBS completed-event collection.
- `src/golf_props/normalization/bootstrap_results.py`: simple bootstrap CSV.
- `src/golf_props/normalization/espn_results.py`: historical ESPN/Kaggle TSV.
- `src/golf_props/normalization/cbs_results.py`: CBS normalization.
- `src/golf_props/normalization/course_identity.py`: conservative course-name
  proposal/audit and accepted-crosswalk validation.
- `src/golf_props/normalization/merge_results.py`: canonical merge; maps
  players by normalized name and applies reviewed course aliases consistently.
- `config/course_aliases.csv`: reviewed source-to-canonical course identities.
- `src/golf_props/normalization/manual_odds.py`: fallback/test odds import.

### Features and performance data

- `src/golf_props/features/player_event.py`: leakage-safe player-event rolling,
  course, major, and Open features.
- `src/golf_props/features/current_event.py`: independent current field and
  strict as-of feature snapshots.
- `src/golf_props/features/round_performance.py`: same-event-round field average
  and relative performance.
- `src/golf_props/analysis/performance_data.py`: canonical readiness audit.

### Models

- `src/golf_props/models/time_split_baseline.py`: base-rate, player rolling, and
  optional logistic baselines.
- `src/golf_props/models/round_strength.py`: indexed point-in-time recency and
  mean/variance shrinkage.
- `src/golf_props/models/tournament_simulator.py`: seeded joint-field Monte
  Carlo simulation.
- `src/golf_props/models/course_adjustment.py`: same-course residual challenger;
  implemented but not promoted.

### Evaluation

- `src/golf_props/backtest/simulation_backtest.py`: walk-forward simulation.
- `src/golf_props/backtest/simulation_selection.py`: validation-only parameter
  grid and later temporal test.
- `src/golf_props/backtest/rolling_simulation_validation.py`: four-fold rolling
  validation, event bootstrap, calibration, and frozen manifest.
- `src/golf_props/backtest/course_challenger_validation.py`: paired incumbent
  versus course challenger with matched seeds.
- `src/golf_props/backtest/current_event_rankings.py`: legacy current-event
  heuristic rankings, not the frozen simulator.
- `src/golf_props/backtest/value_report.py`: joins probability columns to odds.
- `src/golf_props/odds/movement.py`: archived-snapshot movement comparison.

### Operational pipelines

- `src/golf_props/pipelines/current_event_simulation.py`: manifest-driven,
  hash-verified frozen current-event strength, simulation, and reporting.
- `src/golf_props/pipelines/dk_current_value.py`: legacy DraftKings Predictions
  workflow; not the validated simulator path.

### Sportsbook sources

- `src/golf_props/odds/bovada.py`: current working automated source.
- `src/golf_props/odds/draftkings_predictions.py`: parser/tests retained, but
  the live source is stale/unreliable.
- `src/golf_props/odds/covers_inspect.py` and `source_audit.py`: reconnaissance.
- `src/golf_props/pipelines/dk_current_value.py`: historical DK Predictions
  workflow; do not treat it as a reliable current sportsbook path.

All commands are exposed through `src/golf_props/cli.py`.

## Performance Model Evidence

### Round data build

The derived signal is:

```text
relative_to_field = same-event-round field average score - player score
```

Positive means better performance. This normalizes course/event/round scoring
conditions more safely than raw score alone.

### Initial smoke and single-split work

- Five recent events at 1,000 simulations per event were used only as an
  engineering smoke test.
- A later 20-validation-event/10-test-event experiment selected a 180-day
  half-life and 8-round mean prior. It was valid for that experiment, but it is
  superseded as the incumbent choice by the broader rolling result.

### Rolling-origin incumbent result

Four folds selected on one season and evaluated on the following season:

| Evaluation season | Events | Selected half-life | Mean prior | Variance prior |
|---|---:|---:|---:|---:|
| 2022 | 45 | 365 | 8 | 20 |
| 2023 | 44 | 365 | 8 | 20 |
| 2024 | 47 | 365 | 8 | 20 |
| 2025 | 46 | 365 | 8 | 20 |

Aggregate row-weighted Brier improvement versus the structural baseline:

| Target | Improvement |
|---|---:|
| make_cut | +0.0182 |
| top20 | +0.0110 |
| top10 | +0.0053 |
| top5 | +0.0023 |
| winner | +0.0002 |

Equal-event bootstrap results across 182 tournaments:

| Target | Mean improvement | 95% interval | Positive events |
|---|---:|---:|---:|
| make_cut | +0.0160 | [+0.0143, +0.0177] | 88.5% |
| top20 | +0.0116 | [+0.0104, +0.0129] | 93.4% |
| top10 | +0.0065 | [+0.0055, +0.0075] | 91.8% |
| top5 | +0.0034 | [+0.0027, +0.0042] | 88.5% |
| winner | +0.0004 | [+0.0002, +0.0006] | 55.5% |

Bootstrap intervals are conditional on the completed fold selections; the
parameter grid is not rerun inside every bootstrap sample.

Calibration ECE ranges from 0.0086 for top-5 to 0.0260 for make-cut.
Calibration slopes range from 1.16 to 1.29, suggesting probabilities are
somewhat compressed toward average rather than sufficiently dispersed.

Frozen incumbent manifest:

```text
data/interim/reports/rolling_round_simulation_validation/frozen_model_manifest.json
```

Its input hashes were verified after generation. Do not modify this manifest or
the incumbent strength parameters casually.

## Course Challenger Evidence

The challenger estimates same-course residual performance:

1. recency-weight prior rounds at the same canonical course
2. compute the player's same-course mean
3. subtract the player's general weighted mean
4. shrink by effective same-course rounds plus a course prior
5. multiply by a selected adjustment weight
6. cap the absolute adjustment before simulation

Weight 0 was always allowed so the feature could be rejected.

Fold selections:

| Evaluation season | Course weight | Course prior | Evaluation coverage |
|---|---:|---:|---:|
| 2022 | 0.5 | 20 | 61.1% |
| 2023 | 0.5 | 40 | 64.0% |
| 2024 | 0.5 | 8 | 60.1% |
| 2025 | 0.0 | 8 | 56.8% |

Paired aggregate improvement versus the incumbent was only +0.00015 for
make-cut and +0.00005 or less for other placement targets. Paired event
intervals crossed zero for top-20, top-10, top-5, and winner. Winner slightly
worsened. The latest freeze window selected weight 0.5 and a 40-round course
prior after matched-course player coverage rose to 62.9886%.

Decision: do not promote. The incumbent remains unchanged.

Interpretation: repairing identity resolved the latest-window data failure but
did not repair the challenger's instability. Historical folds show that some
same-course signal may exist, but the gain remains too small and unstable; the
2025 fold still selected zero effect.

## Odds Source State

### Bovada: working source

Current endpoint:

```text
https://www.bovada.lv/services/sports/event/coupon/events/A/description/golf/pga-tour
```

The last saved collection report parsed 758 rows:

| Market | Rows |
|---|---:|
| winner | 144 |
| top5 | 144 |
| top10 | 144 |
| top20 | 144 |
| round_leader | 168 |
| make_cut | 14 |

Market availability changes by event and collection time. The parser recognizes
`round_score_ou`, but that market was absent from the last feed.

The Bovada collector currently writes a raw latest JSON payload, normalized
latest CSV, and report. It does not automatically build a complete timestamped
history on every run. Adding durable timestamped Bovada history remains useful,
but it must not block prospective performance validation.

### DraftKings sportsbook: not solved

JavaScript bundles revealed route families under
`sportsbook-nash.draftkings.com`, but direct no-browser requests were blocked by
Akamai. Endpoint strings are not proof of a working collector.

### DraftKings Predictions: stale/unreliable

Parser code and fixtures remain. The source once produced placement rows, then
became unreliable as odds moved behind linked/asynchronous content. Do not use
old reports as proof of current availability.

### FanDuel: desired, not implemented

There is no stable automated no-browser FanDuel collector in the repository.

### Existing value report warning

The saved Bovada value report displays large apparent edges. It is exploratory,
stale, and based on `current-event-rankings`, which uses older rolling-rate and
major/Open heuristics. It does not use the validated frozen round simulator.
Do not cite those rows as evidence of value or betting edge.

## Known Limitations and Open Issues

1. One CBS identity, `Pete Dye Stadium Course PGA West`, remains deliberately
   unresolved because the historical source has no safe equivalent identity.
2. The validated simulator is not integrated into the current Bovada value
   report workflow.
3. Stable timestamped odds history is not yet collected automatically for every
   Bovada run.
4. The benchmark is a structural field baseline, not a strong external model or
   sportsbook closing line.
5. Calibration is decent but probabilities appear compressed.
6. Winner remains a sparse and noisy target despite positive aggregate metrics.
7. Player-name matching still needs occasional aliases.
8. Course par, yardage, turf, and shot-profile features are largely unavailable.
9. Tee times, tee waves, weather, withdrawals, live state, and round/hole stats
   are not modeled.
10. Multi-course and nonstandard event formats are not handled by the simulator.
11. Current results stop before the model freeze date; no genuinely prospective
    tournament has yet been scored with the frozen manifest.
12. No repository commit exists, so project history is not protected by Git.
13. **Playoff event structure:** FedEx St. Jude / BMW / TOUR Championship are
    no-cut. `predict-current-event` now supports an explicit `--cut-rule`
    (`top_n_and_ties` default or `no_cut`) without retuning strength. Under
    `no_cut`, `make_cut_prob` is structural (1.0) and not an empirical target.
14. Local canonical history may lag the market (`source_data_through=2026-07-11`),
    so late-July / early-August completed rounds may be missing from strength.
15. Prospective runs require `--event-start-at-utc` (timezone-aware, strictly
    before run creation time), so the TOUR Championship forecast cannot be
    backfilled after the first tee on Thursday 2026-08-27. The official field is
    only final after BMW concludes on 2026-08-23.

## Completed Task: Course Identity Crosswalk

The reviewed crosswalk is stored at:

```text
config/course_aliases.csv
```

Implementation and evidence:

- the audit command proposed 21 unique exact normalized matches and blocked
  nine rows for review;
- 29 CBS mappings and two historical same-venue consolidations were accepted;
- generic `North Course`, `Oaks Course`, and `Champion Course` mappings were
  accepted only after location/full-venue review;
- `Pete Dye Stadium Course PGA West` remains review-required and unmapped;
- merged `event_courses` and `round_scores` use the same reviewed ID map;
- latest-window player coverage rose from 0% to 62.9886%;
- canonical and round-performance row counts remained unchanged;
- the course-dependent player-event feature file was regenerated with 152,357
  rows;
- the full incumbent rerun reproduced all 365/8/20 fold selections and metrics;
- the paired course challenger was not promoted.

## Completed Task: Frozen Current-Event Workflow

`predict-current-event` now:

1. accepts an independent field, event date, and optional earlier as-of date;
2. verifies the frozen manifest and all recorded input hashes;
3. loads 365/8/20 and cut size from the manifest rather than CLI tuning flags;
4. rejects future as-of dates and non-prospective events by default;
5. permits explicit engineering replays only with `--allow-retrospective`;
6. rejects ambiguous names and unknown supplied IDs while reporting unmatched
   tour-prior fallbacks;
7. runs the seeded joint-field simulator;
8. writes `strengths.csv`, `predictions.csv`, `report.md`, and
   `run_manifest.json` with field, input, manifest, and artifact hashes;
9. records that sportsbook prices and the course challenger were not used;
10. accepts an explicit `--cut-rule` (`top_n_and_ties` default or `no_cut`) and
    logs an `event_structure` block (format, rounds, cut rule, whether a cut
    occurred, frozen manifest cut size, effective advancing field) in the run
    manifest and report;
11. requires a timezone-aware `--event-start-at-utc` for prospective runs and
    rejects runs created at or after that timestamp (`pre_start_verified`).

### Wyndham Championship 2026 dry-run

Current PGA markets were Wyndham Championship starting 2026-08-06. That date
is not strictly after `prospective_holdout_after=2026-08-06`, so the default
prospective command correctly rejected the run.

An engineering dry-run was then executed with `--allow-retrospective`:

- field: `data/raw/fields/wyndham_championship_2026_field.csv` (144 Bovada
  winner-market players; notes in
  `data/raw/fields/wyndham_championship_2026_field_notes.md`)
- output: `data/interim/reports/wyndham_championship_2026_frozen_simulation/`
- classification: `retrospective_replay`
- match status: 7 explicit IDs, 131 name matches, 6 unmatched fallbacks
- amateur/pro ESPN collisions for seven names were resolved to non-`(a)` IDs
- unmatched punctuation/name variants: CT Pan, JT Poston, Kristoffer Ventura,
  Lorenzo Rodriguez, Stephen Jaeger, Thorbjorn Olesen
- highest `top20_prob` ranks were led by Ben Griffin, Cameron Young, Alex
  Fitzpatrick, Justin Thomas, and Maverick McNealy
- this bundle is not prospective evidence and must not be graded as such

## Completed Task: Weekly Forecast Automation

The manual weekly loop (discover event, preserve field, tee times, identity,
archive) is now a generic, idempotent, fail-closed pipeline:

- `src/golf_props/events/event_control.py` — versioned event record and state
  machine (`discovered -> awaiting_field -> awaiting_tee_times ->
  awaiting_identity_resolution -> forecast_ready -> forecast_archived`, plus
  `blocked` and `deadline_missed`; archived/missed are terminal).
- `src/golf_props/ingestion/current_event_discovery.py` — preserves the raw CBS
  schedule and selects the next not-yet-started event; CBS is discovery only and
  never supplies timing or structure.
- `src/golf_props/ingestion/current_field.py` — reviewed **official** field
  evidence (source_kind `official` + finality `final`) unlocks the forecast;
  sportsbook sources are cross-check diagnostics only.
- `src/golf_props/ingestion/tee_times.py` — reviewed tee-time evidence with an
  explicit IANA local timezone derives the earliest Round 1 tee in UTC.
- `src/golf_props/events/structure.py` + `config/event_registry.csv` — reviewed
  per-season scope and event-structure decisions; an event with no reviewed row
  is never selected (fails closed).
- `src/golf_props/normalization/player_identity.py` + `config/player_aliases.csv`
  — reviewed identity resolution (compact-name matching, reviewed aliases,
  ID/name consistency); ambiguous/unknown/unmatched names block.
- `src/golf_props/pipelines/weekly_forecast.py` — orchestrator: runs the frozen
  365/8/20 forecast into a staging directory, copies all evidence, writes an
  `archive_manifest.json` hash index, and atomically promotes to
  `data/interim/reports/prospective_forecasts/<event_key>/`. Refuses overwrite,
  runs at T-12 hours, and never backfills.
- `src/golf_props/backtest/forecast_archive.py` — archive hash verification.
- CLI: `weekly-forecast`, `weekly-forecast-status`, `verify-forecast-archive`,
  `import-current-field-evidence`, `import-current-tee-time-evidence`.

Exit codes: 0 waiting/archived, 10 blocked, 11 deadline missed, 12 identity
blocked, 20 hard error. State lives in `data/interim/weekly/` (`status.json`,
`current_event_key.txt`, `<event_key>/event_control.json`).

Live validation: the pipeline fetched the real CBS schedule, correctly selected
the 2026 TOUR Championship (skipping the in-progress BMW and the excluded
Presidents Cup), and recorded `no_cut` from the reviewed registry. On 2026-08-25
it accepted the preserved official PGA TOUR final field (30 rows) AND reviewed
official Round 1 tee times (earliest tee 2026-08-27T15:00:00Z). All 30 field
identities resolved. The Windows task archived the bundle at T-11 hours on
2026-08-27. After the archive, the loop advanced to the next event and, once
the Biltmore Championship Asheville registry row was added on 2026-08-28, both
hosts moved to `awaiting_field` for it (exit 0, no operator noise). The
scheduled task's exit code 10 (`blocked`) between 2026-08-27 and 2026-08-28 was
the designed unreviewed-next-event signal, not a malfunction.

Frozen-input policy: the weekly pipeline does **not** refresh historical
performance. It continues to use the frozen manifest's hashed inputs
(`source_data_through=2026-07-11`). Any append-only historical refresh is a
separate scientific decision that must not be slipped into operational
automation.

## Exact Next Task: Grade the First Prospective Forecast

### 1. After the 2026 TOUR Championship concludes (Sunday 2026-08-30 / Monday 2026-08-31)

The archive-of-record is
`data/interim/reports/prospective_forecasts/tour_championship_2026/`
(verified on both hosts; `predictions.csv` SHA-256
`412f99b501d33d769c12d1f4d257405a7177d55d0925d1daaa1d72e034276fcb`).

1. Collect official final results for the event (CBS collector is the
   established completed-results source; preserve the raw page first).
2. Grade the frozen `predictions.csv` against actual outcomes for
   top-20/top-10/top-5/winner: Brier/log-loss per target plus calibration
   versus the rolling expectations. `make_cut` is structural (1.0) under
   no-cut and is NOT a graded target.
3. Record the outcome without retuning. Win or lose, the frozen 365/8/20
   incumbent stays unchanged.
4. Update this handoff and the research narrative with the graded result.

### 2. Before 2026-09-10: confirm Bovada markets exist for Biltmore

The Biltmore Championship Asheville registry row is `include=1`
provisionally. Run `collect-bovada-golf-odds` (or check the feed directly)
before 2026-09-10:

- if Biltmore markets appear, leave the row as is;
- if they never appear, flip `include` to 0 (and note why) so the loop skips
  to the next main event.

### 3. Mid-September: arm the Biltmore forecast

When the official field and tee times post (official competitive dates
2026-09-17 to 2026-09-20):

1. preserve official field evidence (`import-current-field-evidence`,
   `source_kind=official`, `finality=final`);
2. preserve official tee times (`import-current-tee-time-evidence`,
   `--local-timezone America/New_York`);
3. the loop archives at T-12 hours automatically (Windows WakeToRun enabled).

### Standing protocol (unchanged)

The event-structure question is resolved in code:

1. **Preferred path (implemented):** explicit, logged event-structure handling
   without changing 365/8/20 strength parameters. Ordinary events use the
   default `top_n_and_ties` cut; playoff events use `--cut-rule no_cut`; all
   prospective runs carry a `--event-start-at-utc` guard.
2. **Forbidden:** inventing a cut that does not exist, backdating a forecast
   after the first tee, counting Wyndham as prospective, or retuning strength
   parameters for one event.

Bovada timestamp collection may continue in parallel. Odds stay outside the
performance model and must not block this loop.

## Core Commands

Run all commands from the repository root with `PYTHONPATH=src`.

### Tests

```bash
PYTHONPATH=src python3 -m pytest
```

### Propose course aliases for review

```bash
PYTHONPATH=src python3 -m golf_props.cli audit-course-crosswalk \
  --base data/processed/espn_pga_2001_2025 \
  --add data/processed/cbs_pga_2026 \
  --output data/interim/reports/course_identity/course_alias_proposals.csv \
  --report-output data/interim/reports/course_identity/proposal_report.md
```

This command never accepts mappings. Review and acceptance occur in
`config/course_aliases.csv`.

### Merge canonical results with reviewed course aliases

```bash
PYTHONPATH=src python3 -m golf_props.cli merge-results \
  --base data/processed/espn_pga_2001_2025 \
  --add data/processed/cbs_pga_2026 \
  --output-dir data/processed/pga_2001_2026 \
  --course-aliases config/course_aliases.csv
```

### Performance data audit

```bash
PYTHONPATH=src python3 -m golf_props.cli audit-performance-data \
  --input-dir data/processed/pga_2001_2026 \
  --output-dir data/interim/reports/performance_data_audit
```

### Build relative round performance

```bash
PYTHONPATH=src python3 -m golf_props.cli build-round-performance \
  --input-dir data/processed/pga_2001_2026 \
  --output data/interim/features/pga_2001_2026_round_performance.csv \
  --report-output data/interim/reports/round_performance/report.md
```

### Build current strength with frozen incumbent parameters

```bash
PYTHONPATH=src python3 -m golf_props.cli build-round-strength \
  --round-performance data/interim/features/pga_2001_2026_round_performance.csv \
  --field data/raw/fields/current_field.csv \
  --output data/interim/features/current_round_strength.csv \
  --report-output data/interim/reports/current_round_strength/report.md \
  --as-of-date YYYY-MM-DD \
  --half-life-days 365 \
  --prior-rounds 8 \
  --variance-prior-rounds 20
```

### Run the frozen current-event workflow

```bash
PYTHONPATH=src python3 -m golf_props.cli predict-current-event \
  --manifest data/interim/reports/rolling_round_simulation_validation/frozen_model_manifest.json \
  --field data/raw/fields/current_field.csv \
  --output-dir data/interim/reports/current_event_frozen_simulation \
  --event-name "Tournament Name" \
  --event-date YYYY-MM-DD \
  --simulations 20000
```

The command rejects a non-prospective event by default. Use
`--allow-retrospective` only for an engineering replay; the resulting run is
permanently labeled `retrospective_replay`.

### Simulate a current tournament

```bash
PYTHONPATH=src python3 -m golf_props.cli simulate-tournament \
  --strengths data/interim/features/current_round_strength.csv \
  --output-dir data/interim/reports/current_tournament_simulation \
  --event-name "Tournament Name" \
  --event-date YYYY-MM-DD \
  --simulations 20000 \
  --seed 20260729
```

### Collect Bovada odds

```bash
PYTHONPATH=src python3 -m golf_props.cli collect-bovada-golf-odds
```

This writes:

```text
data/raw/odds_snapshots/bovada_golf_latest.json
data/processed/odds_snapshots/bovada_golf_latest.csv
data/interim/reports/bovada_golf_odds_collection/report.md
```

### Full rolling incumbent validation

```bash
PYTHONPATH=src python3 -m golf_props.cli rolling-simulation-validation \
  --canonical-dir data/processed/pga_2001_2026 \
  --round-performance data/interim/features/pga_2001_2026_round_performance.csv \
  --output-dir data/interim/reports/rolling_round_simulation_validation \
  --fold 'fold_2022|2021-01-01|2021-12-31|2022-01-01|2022-12-31' \
  --fold 'fold_2023|2022-01-01|2022-12-31|2023-01-01|2023-12-31' \
  --fold 'fold_2024|2023-01-01|2023-12-31|2024-01-01|2024-12-31' \
  --fold 'fold_2025|2024-01-01|2024-12-31|2025-01-01|2025-12-31' \
  --half-life-grid 90,180,365 \
  --prior-rounds-grid 8,20,40 \
  --variance-prior-rounds-grid 20 \
  --freeze-date-from 2025-01-01 \
  --freeze-date-to 2026-07-08 \
  --max-selection-events 20 \
  --max-evaluation-events 0 \
  --selection-simulations 300 \
  --evaluation-simulations 1000 \
  --bootstrap-samples 5000 \
  --calibration-bins 10 \
  --seed 20260729 \
  --cut-size 65
```

### Full paired course challenger

Use the exact command in `README.md` or `docs/implementation_roadmap.md`. It is
computationally heavier than the rolling incumbent run and currently exists to
verify the non-promotion decision after course identity is repaired.

## Important Artifacts

- Research narrative / lessons:
  `docs/research_narrative.md`
- Continuation prompt:
  `docs/continuation_prompt.md`
- Performance audit:
  `data/interim/reports/performance_data_audit/report.md`
- Reviewed course crosswalk:
  `config/course_aliases.csv`
- Course proposal audit:
  `data/interim/reports/course_identity/proposal_report.md`
- Round build:
  `data/interim/reports/round_performance/report.md`
- Rolling report:
  `data/interim/reports/rolling_round_simulation_validation/report.md`
- Frozen incumbent:
  `data/interim/reports/rolling_round_simulation_validation/frozen_model_manifest.json`
- Frozen current-event output contract:
  `strengths.csv`, `predictions.csv`, `report.md`, and `run_manifest.json`
  under the selected event output directory
- Wyndham 2026 retrospective dry-run:
  `data/interim/reports/wyndham_championship_2026_frozen_simulation/`
  (labeled `retrospective_replay`; not prospective evidence)
- Wyndham field notes:
  `data/raw/fields/wyndham_championship_2026_field.csv`
  `data/raw/fields/wyndham_championship_2026_field_notes.md`
- Course challenger report:
  `data/interim/reports/course_challenger_validation/report.md`
- Course challenger manifest:
  `data/interim/reports/course_challenger_validation/challenger_manifest.json`
- Bovada collector report:
  `data/interim/reports/bovada_golf_odds_collection/report.md`
- Windows deployment:
  `docs/windows_deployment.md`
- Git remote:
  `https://github.com/colemason6524/golf_props.git` (`origin`)

Generated artifacts are ignored by Git. Their existence must be checked on the
local machine rather than inferred from repository status.

## Decision Log

### Keep

- Performance-first development independent of odds access.
- Event-round-relative scoring.
- Indexed strict as-of histories.
- 365/8/20 round-strength incumbent.
- Joint-field seeded simulation.
- Hash-verified, manifest-driven current-event forecasts.
- Explicit, logged no-cut / field-size event-structure support separate from
  frozen strength parameters.
- Pre-start timestamp verification so prospective forecasts cannot be backfilled
  after tee time.
- Rolling-origin selection and evaluation.
- Tournament-level paired bootstrap.
- Reviewed and auditable cross-source course identity.
- Bovada as the current automated odds source.
- Explicit retrospective labeling instead of loosening prospective rules.
- Unequal-phase progress framing: advanced foundation, early prospective/edge.

### Rejected or deferred

- Heavy dependence on odds before the performance brain is credible.
- Treating DraftKings endpoint strings as a solved collector.
- Treating DraftKings Predictions as reliable live odds.
- Promoting the current same-course residual challenger.
- Treating the legacy value report as betting-edge evidence.
- Calling Wyndham a prospective holdout.
- Live/in-progress modeling at this stage.
- Paid API dependence as the initial foundation.
- Blind application of top-65 cut assumptions to FedExCup Playoffs events.

### Superseded

- The 180-day/8-round parameter result from the single temporal split is
  superseded by the four-fold 365-day/8-round result for incumbent use.

## New Session Checklist

1. Confirm the workspace is `/Users/colemason/Documents/golf_props`.
2. Read `AGENTS.md`, this entire handoff, and `docs/research_narrative.md`.
3. Run `git status --short --branch` and `git pull` against `origin/main` when a
   remote sync is wanted; preserve all untracked files.
4. Run `PYTHONPATH=src python3 -m pytest`.
5. Inspect the frozen manifests and confirm generated data still exists.
6. Resolve the playoff no-cut / event-structure question before forecasting
   playoff events. Explicit `--cut-rule no_cut` support is now implemented;
   strength parameters are unchanged.
7. The generic `weekly-forecast` loop is live and fail-closed. It waits for
   reviewed official field/tee-time evidence, so the operator must preserve
   that evidence after BMW concludes (2026-08-23) and after tee times post. Add
   each next event to `config/event_registry.csv` and unresolved names to
   `config/player_aliases.csv`; the pipeline blocks rather than guessing. Run
   `weekly-forecast-status` to see why it is waiting.
8. Update this handoff, the research narrative, and the continuation prompt
   whenever a decision, experiment, source status, frozen parameter, cutoff, or
   next task changes.

The copy-ready prompt for a new session is stored at
`docs/continuation_prompt.md`.
