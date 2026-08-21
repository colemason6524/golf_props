# Golf Props Research Prototype

This repository is a research scaffold for PGA golf props. The goal is to
estimate golfer performance probabilities from historical form, course fit,
field context, weather/course conditions, and market prices, then compare those
probabilities to sportsbook lines.

## Continuity: Start Here

For a complete takeover snapshot, read
[docs/project_handoff.md](/Users/colemason/Documents/golf_props/docs/project_handoff.md).
It records the current architecture, verified results, frozen model, rejected
challenger, source status, scientific constraints, exact next task, commands,
and artifact locations.

For the research story—successes, failures, current theory, and outward
risks—read
[docs/research_narrative.md](/Users/colemason/Documents/golf_props/docs/research_narrative.md).

A copy-ready new-session prompt lives at
[docs/continuation_prompt.md](/Users/colemason/Documents/golf_props/docs/continuation_prompt.md).

Progress framing: do not call this project literally “halfway done.” The
performance-model foundation is advanced; prospective validation and market-edge
research are still early. The binding gap is prospective evidence.

The project borrows the same discipline as the horse racing research repo:

- raw-source-first collection
- canonical tables before modeling
- timestamped odds snapshots
- leakage-safe historical features
- market baselines before value claims
- simple backtests before richer models

## Current Scope

- PGA Tour first
- Bovada is the current working no-browser odds source
- FanDuel and DraftKings remain desired source references, but are not the
  current automated backbone
- Avoid paid APIs and avoid manual odds entry as the normal workflow
- Heavy emphasis on historical results, course history, recent form, and live
  line collection
- Research only; no real-money betting automation

## Current Implementation Status

The project is now a runnable Python research prototype, not just docs:

- historical result normalization exists for bootstrap, ESPN/Kaggle-style TSVs,
  CBS collected results, and merged canonical result directories
- leakage-safe player-event feature generation exists
- time-split baseline modeling exists for base-rate, rolling-player, and
  logistic baselines
- event-round-relative performance, recency-weighted strength estimation, and
  field-level tournament simulation exist
- a manifest-driven `predict-current-event` command now verifies frozen inputs,
  locks 365/8/20 parameters, classifies prospective eligibility, and writes a
  reproducible performance-only forecast bundle
- the simulator supports an explicit `no_cut` event-structure rule in addition
  to the ordinary `top_n_and_ties` cut, and prospective runs require a
  timezone-aware `--event-start-at-utc` timestamp that is strictly before the
  run's creation time (no post-tee-time backfilling)
- a walk-forward simulator backtest compares performance probabilities with
  simple field-structure baselines
- validation-only simulator parameter selection and a later untouched temporal
  test are implemented
- four-fold rolling-origin validation, whole-event bootstrap intervals,
  calibration diagnostics, and a frozen incumbent manifest are implemented
- an auditable reviewed course crosswalk now links ESPN history to CBS 2026
  venues; a paired same-course residual challenger was rerun but not promoted
- current-event ranking and value-report generation exist
- odds movement reporting exists for archived snapshots
- DraftKings Predictions parsing exists but is not reliable as a live current
  source after the site changed its rendering/linked-page behavior
- Bovada PGA odds collection works from a no-browser JSON endpoint and writes
  canonical `odds_snapshots` rows

The latest working Bovada collection path produced:

- `data/processed/odds_snapshots/bovada_golf_latest.csv`
- `data/raw/odds_snapshots/bovada_golf_latest.json`
- `data/interim/reports/bovada_golf_odds_collection/report.md`
- `data/interim/reports/bovada_golf_current_event_rankings/report.md`
- `data/interim/reports/bovada_golf_current_value_report/report.md`

The ranking/value artifacts in that list are legacy exploratory outputs built
from rolling-rate heuristics, not the validated frozen tournament simulator.
Their displayed edges are not evidence of a betting advantage.

## First Markets

The first modeling targets should be markets that are clear to grade and close
to player-performance prediction:

- make cut
- top 20 / top 10 / top 5
- winner as a monitored but noisy market
- head-to-head tournament matchups
- round score or round finishing props once round-level collection is stable

Outrights are included because books post them broadly, but they are sparse,
noisy, and harder to validate early. Treat early outright value as exploratory,
especially for longshots.

## Runtime

Use Python 3.9+ from the project root. During local development either install
the package or set `PYTHONPATH=src`.

Install dependencies:

```bash
python3 -m pip install -e ".[dev]"
```

Run tests:

```bash
PYTHONPATH=src python3 -m pytest
```

Collect the current Bovada PGA odds snapshot:

```bash
PYTHONPATH=src python3 -m golf_props.cli collect-bovada-golf-odds
```

Build current-event rankings from the Bovada field:

```bash
PYTHONPATH=src python3 -m golf_props.cli current-event-rankings \
  --features data/interim/features/pga_2001_2026_player_event_features.csv \
  --odds data/processed/odds_snapshots/bovada_golf_latest.csv \
  --output-dir data/interim/reports/bovada_golf_current_event_rankings \
  --event-date 2026-07-30 \
  --top-n 25
```

Build a Bovada value report:

```bash
PYTHONPATH=src python3 -m golf_props.cli value-report \
  --rankings data/interim/reports/bovada_golf_current_event_rankings/event_rankings.csv \
  --odds data/processed/odds_snapshots/bovada_golf_latest.csv \
  --output-dir data/interim/reports/bovada_golf_current_value_report \
  --top-n 50
```

Adjust `--event-date` for the actual tournament start date. Current-event
ranking is pre-tournament oriented; live round state is not required.

## Performance-First Workflow

Sportsbook prices are a separate comparison layer, not a required input to the
performance model. Audit the canonical performance data with:

```bash
PYTHONPATH=src python3 -m golf_props.cli audit-performance-data \
  --input-dir data/processed/pga_2001_2026 \
  --output-dir data/interim/reports/performance_data_audit
```

Audit course identities before merging a new result source:

```bash
PYTHONPATH=src python3 -m golf_props.cli audit-course-crosswalk \
  --base data/processed/espn_pga_2001_2025 \
  --add data/processed/cbs_pga_2026 \
  --output data/interim/reports/course_identity/course_alias_proposals.csv \
  --report-output data/interim/reports/course_identity/proposal_report.md
```

The audit only proposes unique exact normalized/token matches. A reviewer must
explicitly accept mappings in `config/course_aliases.csv`; generic names are
never accepted automatically. Apply the reviewed file consistently to courses,
event-course rows, and round scores with:

```bash
PYTHONPATH=src python3 -m golf_props.cli merge-results \
  --base data/processed/espn_pga_2001_2025 \
  --add data/processed/cbs_pga_2026 \
  --output-dir data/processed/pga_2001_2026 \
  --course-aliases config/course_aliases.csv
```

Current-event features can be built from an independent field CSV. The minimum
field contract is:

```csv
player_name,entry_status
Scottie Scheffler,confirmed
Rory McIlroy,confirmed
```

An optional `player_id` column may be supplied when the canonical ID is known.
Build a point-in-time feature snapshot with:

```bash
PYTHONPATH=src python3 -m golf_props.cli build-current-event-features \
  --input-dir data/processed/pga_2001_2026 \
  --field data/raw/fields/current_field.csv \
  --output data/interim/features/current_event_features.csv \
  --report-output data/interim/reports/current_event_features/report.md \
  --event-name "Tournament Name" \
  --event-date YYYY-MM-DD \
  --course-name "Course Name"
```

Only events completed strictly before `--event-date` enter these features. The
output has blank targets, records the latest history date used per player, and
reports unmatched or ambiguous field names. Sportsbook odds are not read by
this command.

Build the performance-only round and simulation pipeline:

```bash
PYTHONPATH=src python3 -m golf_props.cli build-round-performance \
  --input-dir data/processed/pga_2001_2026 \
  --output data/interim/features/pga_2001_2026_round_performance.csv \
  --report-output data/interim/reports/round_performance/report.md

PYTHONPATH=src python3 -m golf_props.cli build-round-strength \
  --round-performance data/interim/features/pga_2001_2026_round_performance.csv \
  --field data/raw/fields/current_field.csv \
  --output data/interim/features/current_round_strength.csv \
  --report-output data/interim/reports/current_round_strength/report.md \
  --as-of-date YYYY-MM-DD

PYTHONPATH=src python3 -m golf_props.cli simulate-tournament \
  --strengths data/interim/features/current_round_strength.csv \
  --output-dir data/interim/reports/current_tournament_simulation \
  --event-name "Tournament Name" \
  --event-date YYYY-MM-DD \
  --simulations 20000 \
  --seed 20260729
```

Positive round performance means strokes better than the same event-round
field average. Scores outside the default plausible 18-hole range of 58–110
are excluded and counted in the quality report. Strength estimates use
exponential recency decay, small-sample shrinkage, and variance shrinkage.
Tournament simulation uses discrete score draws, applies a top-65-and-ties cut,
and produces coherent probabilities without sportsbook inputs.

For an operational forecast, use the frozen manifest rather than passing model
parameters manually:

```bash
PYTHONPATH=src python3 -m golf_props.cli predict-current-event \
  --manifest data/interim/reports/rolling_round_simulation_validation/frozen_model_manifest.json \
  --field data/raw/fields/current_field.csv \
  --output-dir data/interim/reports/current_event_frozen_simulation \
  --event-name "Tournament Name" \
  --event-date YYYY-MM-DD \
  --simulations 20000
```

The command verifies the frozen canonical and round-performance hashes, uses
the manifest's 365/8/20 parameters and cut size, and writes `strengths.csv`,
`predictions.csv`, `report.md`, and `run_manifest.json`. Events must start
strictly after the manifest's prospective threshold. Historical engineering
replays require `--allow-retrospective` and are permanently labeled
`retrospective_replay`; they are not prospective evidence.

Event structure is an explicit logged decision, separate from the frozen
strength parameters:

- `--cut-rule top_n_and_ties` (default) applies the frozen top-65-and-ties cut.
- `--cut-rule no_cut` advances every active player; `make_cut_prob` becomes
  structural (1.0) and is not an empirical target for such events.

Prospective runs also require `--event-start-at-utc` with a timezone-aware
timestamp (for example `2026-08-27T13:00:00Z`). The run is rejected if created
at or after that timestamp, so a forecast cannot be backfilled after tee time.
The output `run_manifest.json` records an `event_structure` object with the
applied rule, whether a cut occurred, the frozen manifest cut size, and the
effective advancing field size.

Run an exploratory walk-forward evaluation with:

```bash
PYTHONPATH=src python3 -m golf_props.cli simulation-backtest \
  --canonical-dir data/processed/pga_2001_2026 \
  --round-performance data/interim/features/pga_2001_2026_round_performance.csv \
  --output-dir data/interim/reports/round_simulation_backtest \
  --max-events 10 \
  --simulations 2000
```

Select decay/shrinkage parameters on validation events and evaluate the selected
configuration once on a later test window with:

```bash
PYTHONPATH=src python3 -m golf_props.cli simulation-model-selection \
  --canonical-dir data/processed/pga_2001_2026 \
  --round-performance data/interim/features/pga_2001_2026_round_performance.csv \
  --output-dir data/interim/reports/round_simulation_model_selection \
  --validation-date-from 2024-01-01 \
  --validation-date-to 2025-12-31 \
  --test-date-from 2026-01-01 \
  --test-date-to 2026-08-04 \
  --half-life-grid 90,180,365 \
  --prior-rounds-grid 8,20,40 \
  --variance-prior-rounds-grid 20 \
  --max-validation-events 20 \
  --max-test-events 10 \
  --validation-simulations 300 \
  --test-simulations 1000
```

The first run selected a 180-day half-life and an 8-round mean prior. Across
the later 10-event test, Brier improvement versus the structural baseline was
positive for make-cut (+0.0166), top-20 (+0.0137), top-10 (+0.0040), and top-5
(+0.0016), while winner was essentially flat (-0.00004). This is encouraging
performance-model evidence, not a betting-edge result.

Run repeated rolling-origin validation, event-level uncertainty intervals, and
calibration diagnostics with:

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
  --selection-simulations 300 \
  --evaluation-simulations 1000 \
  --bootstrap-samples 5000
```

The four evaluation folds cover 182 tournaments and 22,567–22,570 graded
player-target rows. Every fold selected a 365-day half-life with an 8-round
mean prior. Equal-event bootstrap mean Brier improvements and 95% intervals
were +0.0160 `[+0.0143, +0.0177]` for make-cut, +0.0116
`[+0.0104, +0.0129]` for top-20, +0.0065 `[+0.0055, +0.0075]` for top-10,
and +0.0034 `[+0.0027, +0.0042]` for top-5. The intervals are conditional on
the completed fold selections; parameter selection is not rerun inside every
bootstrap sample.

Evaluate a same-course residual challenger against the incumbent with the same
folds and matched simulation seeds:

```bash
PYTHONPATH=src python3 -m golf_props.cli course-challenger-validation \
  --canonical-dir data/processed/pga_2001_2026 \
  --round-performance data/interim/features/pga_2001_2026_round_performance.csv \
  --output-dir data/interim/reports/course_challenger_validation \
  --fold 'fold_2022|2021-01-01|2021-12-31|2022-01-01|2022-12-31' \
  --fold 'fold_2023|2022-01-01|2022-12-31|2023-01-01|2023-12-31' \
  --fold 'fold_2024|2023-01-01|2023-12-31|2024-01-01|2024-12-31' \
  --fold 'fold_2025|2024-01-01|2024-12-31|2025-01-01|2025-12-31' \
  --course-weight-grid 0,0.5,1 \
  --course-prior-rounds-grid 8,20,40 \
  --freeze-date-from 2025-01-01 \
  --freeze-date-to 2026-07-08
```

The challenger rerun after course identity repair did not justify promotion.
Latest-window matched-course player coverage rose from 0% to 62.9886%, and its
selector chose course weight 0.5 with a 40-round course prior. However, the
2025 rolling fold still chose weight 0; aggregate make-cut Brier improvement
remained only +0.00015; paired intervals crossed zero for top-20, top-10,
top-5, and winner; and winner slightly worsened. The incumbent therefore
remains unchanged.

## Known Limitations

- Bovada currently works for PGA pre-tournament markets, but market availability
  varies by event and time. The current live Rocket Classic snapshot included
  winner, top 5, top 10, top 20, first-round leader, and a smaller make-cut set.
- Round score over/under is supported by the Bovada parser, but it was not
  present in the latest current PGA feed at the time of implementation.
- DraftKings sportsbook backend routes were discoverable in site bundles but
  direct no-browser requests were blocked by Akamai. DraftKings Predictions had
  worked for placement markets, then became unreliable when odds moved behind
  asynchronous/linked content.
- FanDuel remains a desired book, but no stable no-browser collector exists
  here yet.
- Reports are exploratory. Do not claim a betting edge until enough
  out-of-sample events and stable odds coverage are archived.
- Some player matching still falls back to base rates when Bovada names differ
  from historical data, for example punctuation/spacing variants.
- Rolling-origin evidence now covers four folds and 182 evaluation events, but
  the benchmark remains a structural field baseline rather than sportsbook
  prices or a strong external golf model. Calibration slopes above 1 indicate
  compressed probabilities, and event-bootstrap intervals do not include
  parameter-selection uncertainty.
- The frozen future configuration must only be evaluated on tournaments
  starting after both the source-data cutoff and model-freeze date recorded in
  `frozen_model_manifest.json`. Previously inspected events must not be reused
  as a supposedly untouched holdout.
- Event-relative score is a public-data proxy, not official ShotLink strokes
  gained. The cut model currently assumes ordinary 72-hole stroke play with a
  top-65-and-ties cut.
- A same-course residual challenger exists but did not earn promotion after
  cross-source identity repair. The reviewed crosswalk restores 62.9886%
  latest-window player coverage. `Pete Dye Stadium Course PGA West` remains
  deliberately unresolved because the historical source contains no safe
  equivalent identity.
- Tee-wave, weather, withdrawal-risk, multi-course, and nonstandard event-format
  adjustments are not yet part of the simulation.
- FedExCup Playoffs events are no-cut. Explicit `no_cut` support exists so the
  frozen simulator can represent them honestly (30-player TOUR Championship is
  the next eligible prospective event: 72-hole stroke play, no cut, all players
  at even par). St. Jude and BMW could not be forecast prospectively because
  their windows closed before the no-cut path was available.
- No genuinely prospective frozen forecast has been archived yet as of
  2026-08-20. Wyndham 2026 was a retrospective engineering replay only.

## Core Question

Can we build a point-in-time-safe golfer-event dataset that predicts player
outcomes better than the market baseline, especially after accounting for:

- current form
- course history
- course fit
- field strength
- hole/round scoring tendencies
- weather and tee-time wave conditions
- market movement

See [docs/prototype_plan.md](/Users/colemason/Documents/golf_props/docs/prototype_plan.md)
for the initial build plan.

See [docs/implementation_roadmap.md](/Users/colemason/Documents/golf_props/docs/implementation_roadmap.md)
for the concrete phase-by-phase execution roadmap.

See [docs/source_recon_phase1.md](/Users/colemason/Documents/golf_props/docs/source_recon_phase1.md)
for the first source reconnaissance notes.

See [docs/source_evaluation_matrix.md](/Users/colemason/Documents/golf_props/docs/source_evaluation_matrix.md)
for the first source-by-source usefulness review.

See [docs/canonical_schema.md](/Users/colemason/Documents/golf_props/docs/canonical_schema.md)
for the proposed canonical tables.

See [docs/project_handoff.md](/Users/colemason/Documents/golf_props/docs/project_handoff.md)
for the authoritative current state and exact continuation point.

See [docs/research_narrative.md](/Users/colemason/Documents/golf_props/docs/research_narrative.md)
for the story of what was learned and what to watch for next.

See [docs/continuation_prompt.md](/Users/colemason/Documents/golf_props/docs/continuation_prompt.md)
for the copy-ready new-session prompt.
