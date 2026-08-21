# Golf Props Project Handoff

Last updated: 2026-08-10

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

## Exact Stopping Point

No command or background process is currently running. Documentation was
refreshed on 2026-08-10 for conversation handoff. The frozen current-event
workflow is complete. A Wyndham Championship dry-run was archived as an
explicitly labeled retrospective replay; it is not prospective evidence.

As of 2026-08-10 evening local time:

- no genuinely prospective frozen forecast has been archived yet;
- the next PGA event after Wyndham is the FedEx St. Jude Championship
  (competitive dates 2026-08-13 to 2026-08-16);
- that event is a FedExCup Playoffs no-cut ~69-player field, which conflicts
  with the simulator’s ordinary top-65-and-ties cut assumption;
- frozen manifest parameters and incumbent strength settings remain unchanged.

The next queued task is:

> Resolve the event-structure question for the first prospective forecast, then
> archive an authoritative independent field and run the first genuinely
> prospective frozen forecast for an event starting after 2026-08-06.

Preserve that forecast bundle unchanged for later grading. Keep sportsbook
prices outside the performance computation, and do not use a retrospective
replay as prospective evidence. Do not modify the frozen strength parameters
(365/8/20) while addressing event structure.

## Git and Workspace State

As of this handoff:

```text
## No commits yet on main
?? .gitignore
?? AGENTS.md
?? README.md
?? config/
?? docs/
?? logs/
?? pyproject.toml
?? src/
?? tests/
```

There are no commits. The unusual all-untracked state is expected. Do not run
`git clean`, reset, delete, or revert files. Large generated/research data under
`data/raw`, `data/processed`, and `data/interim` is intentionally ignored by
`.gitignore`, but it is essential local research state.

The latest verified test result at handoff refresh:

```text
107 passed
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
13. **Playoff event structure:** FedEx St. Jude / BMW / TOUR Championship do not
    match the ordinary top-65-and-ties cut assumption. `predict-current-event`
    currently locks `cut_size` from the frozen manifest and has no first-class
    no-cut mode.
14. Local canonical history may lag the market (`source_data_through=2026-07-11`),
    so late-July / early-August completed rounds may be missing from strength.
15. The St. Jude prospective window closes at Thursday 2026-08-13 tee times; do
    not backfill after the event starts.

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
9. records that sportsbook prices and the course challenger were not used.

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

## Exact Next Task: First Prospective Forecast

### Immediate decision required before running St. Jude

FedEx St. Jude Championship (2026-08-13 start) is date-eligible and is the
calendar-next PGA event, but it is a **no-cut playoff event**. Do not run the
frozen workflow with an ordinary top-65 cut and call that a valid prospective
test.

Choose one explicit path and document it:

1. **Preferred if feasible before tee time:** add an explicit, logged event-
   structure handling for no-cut / field-size cut without changing 365/8/20
   strength parameters; then forecast St. Jude prospectively.
2. **Honest alternative:** skip playoff no-cut / special-format events for the
   first prospective series and wait for the next ordinary full-field cut
   event after the playoffs.
3. **Forbidden:** backdating a forecast after Thursday tee times, counting
   Wyndham as prospective, or retuning strength parameters for one event.

### Prospective protocol once event structure is honest

1. preserve an authoritative independent field CSV before the event starts
   (official PGA Tour / FedExCup field preferred; Bovada only as cross-check);
2. run `predict-current-event` without `--allow-retrospective`;
3. resolve unsafe field identities rather than bypassing them;
4. archive the complete output bundle unchanged;
5. after the event, grade the frozen probabilities without retuning;
6. repeat across multiple events to evaluate prospective calibration and
   stability.

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
3. Run `git status --short --branch` and preserve all untracked files.
4. Run `PYTHONPATH=src python3 -m pytest`.
5. Inspect the frozen manifests and confirm generated data still exists.
6. Resolve the playoff no-cut / event-structure question before forecasting
   St. Jude or BMW.
7. Start the first genuinely prospective frozen forecast only under honest
   event-structure assumptions unless the user explicitly changes direction.
8. Update this handoff, the research narrative, and the continuation prompt
   whenever a decision, experiment, source status, frozen parameter, cutoff, or
   next task changes.

The copy-ready prompt for a new session is stored at
`docs/continuation_prompt.md`.
