# Canonical Schema

Date: 2026-07-16

Last updated: 2026-08-06

## Purpose

Define the first normalized table contracts for PGA golf props research. Source
adapters can emit messy source-local records, but model and backtest code should
depend on these canonical shapes.

## Tables

### `events`

- `event_id` primary key
- `source`
- `source_event_id`
- `tour`
- `season`
- `event_name`
- `date_start`
- `date_end`
- `timezone`
- `format`
- `is_major`
- `is_alternate_field`
- `created_at_utc`

### `courses`

- `course_id` primary key
- `source`
- `source_course_id`
- `course_name`
- `location`
- `country`
- `par`
- `yardage`
- `grass_type`
- `latitude`
- `longitude`
- `created_at_utc`

### `course_aliases`

- `source`
- `source_course_id`
- `source_course_name`
- `canonical_course_id`
- `canonical_course_name`
- `match_method`
- `confidence`
- `review_status`
- `notes`

Implemented in `config/course_aliases.csv` and copied into merged canonical
directories as `course_aliases.csv`. `review_status=accepted` is the only state
that can change canonical IDs. Proposed and review-required rows are inert.

`audit-course-crosswalk` HTML-unescapes, Unicode-normalizes, expands safe
abbreviations, strips only trailing location-shaped suffixes, and proposes
unique exact normalized or exact token-set matches. It never accepts a
proposal. Generic names such as `North Course`, `Oaks Course`, and
`Champion Course` are blocked pending venue/location review.

`merge-results --course-aliases ...` validates every accepted source identity
and canonical target, then applies one course-ID map to both `event_courses`
and `round_scores`. Source IDs and names remain in the copied crosswalk for
auditability. The reviewed 2026 repair accepts 31 alias rows (29 CBS-to-ESPN
and two historical same-venue consolidations) and deliberately leaves the CBS
`Pete Dye Stadium Course PGA West` identity unresolved because no equivalent
historical source course was found.

### `event_courses`

- `event_id`
- `course_id`
- `round_number`
- `is_primary_course`
- `notes`

This table matters for multi-course events and courses that rotate across
events.

### `players`

- `player_id` primary key
- `source`
- `source_player_id`
- `player_name`
- `country`
- `handedness`
- `date_of_birth`
- `created_at_utc`

### `field_entries`

- `entry_id` primary key
- `event_id`
- `player_id`
- `entry_status`
- `tee_time_local`
- `tee_time_utc`
- `starting_hole`
- `wave`
- `captured_at_utc`

### `round_scores`

- `round_score_id` primary key
- `event_id`
- `course_id`
- `player_id`
- `round_number`
- `score`
- `to_par`
- `position_after_round`
- `made_cut_status`
- `started_at_utc`
- `completed_at_utc`
- `recorded_at_utc`

### `hole_scores`

- `hole_score_id` primary key
- `event_id`
- `course_id`
- `player_id`
- `round_number`
- `hole_number`
- `par`
- `yardage`
- `score`
- `to_par`
- `recorded_at_utc`

### `player_event_results`

- `result_id` primary key
- `event_id`
- `player_id`
- `finish_position`
- `finish_text`
- `made_cut`
- `withdrawn`
- `disqualified`
- `total_score`
- `total_to_par`
- `rounds_played`
- `earnings`
- `recorded_at_utc`

### `player_event_stats`

- `stat_row_id` primary key
- `event_id`
- `player_id`
- `stat_name`
- `stat_value`
- `stat_rank`
- `round_number`
- `recorded_at_utc`

Stat names may include:

- `sg_total`
- `sg_ott`
- `sg_app`
- `sg_arg`
- `sg_putt`
- `driving_distance`
- `driving_accuracy`
- `gir`
- `scrambling`
- `birdies`
- `bogeys`
- `par_3_scoring`
- `par_4_scoring`
- `par_5_scoring`

### `weather_snapshots`

- `weather_id` primary key
- `event_id`
- `course_id`
- `round_number`
- `forecast_or_observed`
- `captured_at_utc`
- `valid_at_utc`
- `temperature_f`
- `wind_speed_mph`
- `wind_gust_mph`
- `wind_direction`
- `precipitation_probability`
- `precipitation_amount`
- `notes`

### `odds_snapshots`

- `odds_id` primary key
- `event_id`
- `event_name`
- `season`
- `player_id`
- `player_name`
- `sportsbook`
- `market_type`
- `market_name`
- `selection_name`
- `line`
- `price_american`
- `price_decimal`
- `implied_probability`
- `captured_at_utc`
- `source_url`
- `market_status`
- `is_closing_candidate`

Implemented `market_type` values:

- `make_cut`
- `top20`
- `top10`
- `top5`
- `winner`
- `round_leader`
- `round_score_ou`

Expected future `market_type` values:

- `head_to_head`
- `birdies`
- `bogeys`
- `greens_in_regulation`
- `fairways_hit`

Naming note:

Code currently uses compact top-N names (`top20`, `top10`, `top5`) and
`winner`, not `top_20` or `outright`. Documentation and new parsers should
follow the implemented names unless the schema is intentionally migrated.

### `market_results`

- `market_result_id` primary key
- `event_id`
- `player_id`
- `market_type`
- `line`
- `result_value`
- `did_cash`
- `graded_at_utc`
- `grading_source`

### `features_player_event`

- `feature_row_id` primary key
- `event_id`
- `player_id`
- `feature_timestamp_utc`
- `recent_rounds_count`
- `recent_score_avg`
- `recent_score_weighted`
- `recent_made_cut_rate`
- `recent_top20_rate`
- `course_starts`
- `course_made_cut_rate`
- `course_top20_rate`
- `course_avg_finish`
- `course_avg_score_to_par`
- `field_strength_rank`
- `owgr_rank`
- `target_make_cut`
- `target_top20`
- `target_top10`
- `target_top5`
- `target_win`

## Leakage Rule

For a player-event row at `feature_timestamp_utc = T`, features may only use
records with timestamps strictly earlier than `T`. If a source only has event
dates, use conservative event ordering and exclude the current event entirely.

## First Validation Rules

- Every result row must map to one event and one player.
- Every odds row must include sportsbook, market type, price, and capture time.
- Every automated odds collector should save raw source data before normalized
  CSV output when feasible.
- Every event-level model row must have an event date before labels are joined.
- Course-history features must exclude the current event.
- Round-level features must exclude future rounds in the same event.

## Current Field Input Contract

Performance-only current-event forecasts accept a small field CSV independent
of sportsbook odds. Required:

- `player_name`

Optional:

- `player_id`
- `entry_status`

`build-current-event-features` matches this field to canonical players and
writes the ordinary player-event feature columns with blank targets, plus:

- `player_match_status`
- `history_through_date`

Historical events are eligible only when their completion date is strictly
earlier than the requested current event date. This ensures the most recently
completed start is included without admitting an in-progress or future event.

## Derived Performance Tables

### `round_performance`

- event and player identity
- event start and completion dates
- round number and observed score
- same-event-round field average and field size
- `relative_to_field`

`relative_to_field = field average score - player score`, so positive values
mean better performance. The builder excludes scores outside 58–110 by default
and reports them. This is a public-results proxy, not official strokes gained.

### `round_strength`

- player identity and field match status
- as-of date and decay-weighted round count
- history start/end dates
- long-term and recent-window relative performance
- recency-weighted and shrunk expected relative performance
- raw and shrunk performance standard deviation

Only completed prior events are eligible. The decay-weight sum is the
current-equivalent sample size, so old histories lose reliability and shrink
toward the tour mean.

### `tournament_simulation_predictions`

- event and player identity
- source strength and uncertainty
- make-cut, top-20, top-10, top-5, and winner probability
- conditional finish summaries
- simulation count and random seed

All players are simulated together, so placement probabilities are conditional
on the supplied field rather than independent binary estimates.

### Frozen current-event forecast bundle

`predict-current-event` writes:

- `strengths.csv`: point-in-time round strength using parameters loaded from
  the frozen incumbent manifest
- `predictions.csv`: seeded joint-field placement probabilities
- `report.md`: prospective/retrospective classification, field diagnostics,
  frozen parameters, and performance-only rankings
- `run_manifest.json`: frozen-manifest hash, verified source hashes, field
  hash, artifact hashes, dates, eligibility status, match warnings, parameters,
  simulation count, seed, and cut size

The command rejects stale frozen inputs, a future as-of date, ambiguous player
names, unknown supplied player IDs, and non-prospective events by default.
Unmatched names remain explicit tour-prior fallbacks. A historical replay
requires an explicit override and is permanently labeled retrospective.
Sportsbook prices and the unpromoted course challenger are not consumed.

### Simulation evaluation artifacts

`simulation-model-selection` writes a validation grid with the decay and
shrinkage parameters, target-level normalized Brier skill, and one selected
row. It also records the exact validation/test date boundaries, simulation
counts, seed, objective, and selected parameters in JSON. Full predictions,
metrics, calibration buckets, and reports are retained separately for the
selected validation run and the later untouched test run. The windows must not
overlap, and winner is excluded from the selection objective because its event
rate is too sparse for the initial grid.

`rolling-simulation-validation` adds:

- explicit selection and following evaluation boundaries for every fold
- the parameters frozen independently by each fold
- concatenated out-of-sample predictions and target/fold metrics
- paired Brier improvements resampled at the whole-tournament level
- equal-frequency calibration buckets, ECE, and calibration intercept/slope
- a frozen-model JSON manifest containing the latest selected parameters,
  source-data cutoff, freeze timestamp, random seed, input file hashes, and
  next-evaluation rule

Evaluation windows cannot overlap. The event-bootstrap intervals quantify
event-sampling variation conditional on the completed fold selections; the
parameter search is not rerun inside each bootstrap sample. An event qualifies
as genuinely future evidence only when its start date is later than both the
manifest's `source_data_through` completion-date cutoff and model-freeze date.

### Course-residual challenger artifacts

The course challenger indexes prior `round_performance` by player and canonical
course. For an event starting at `T`, only rounds from events completed before
`T` are eligible. It computes a recency-weighted same-course mean, subtracts the
player's general weighted mean, shrinks that residual by effective course
rounds, and caps the resulting adjustment before tournament simulation.

`course-challenger-validation` selects course adjustment weight and course
prior only inside each fold's historical selection window. Weight 0 is always
an eligible candidate, allowing the feature to be rejected. Incumbent and
challenger use identical fields, outcomes, and simulation seeds. Outputs retain
paired predictions, fold metrics, paired whole-event bootstrap intervals,
calibration comparisons, course-history coverage, and a hashed research-
challenger manifest. Positive paired improvement means the challenger beat the
incumbent, not merely the structural field baseline.

After the reviewed crosswalk was applied, the latest 20-event freeze window
rose from 0% to 62.9886% matched-course player coverage. The rerun selected
weight 0.5/prior 40 in that latest window, but the 2025 rolling fold still
selected weight 0 and paired bootstrap intervals crossed zero for top-20
through winner. The challenger therefore remains research-only and the
365-day/8-round/20-round-variance incumbent remains unchanged.

## Current Source-Specific Notes

### Bovada

`src/golf_props/odds/bovada.py` maps Bovada's nested event/display-group/market
JSON into `odds_snapshots`.

Important normalization behavior:

- Bovada splits one tournament into path/event groups such as `Rocket Classic`,
  `Rocket Classic - Finishes`, and `Rocket Classic - Specials`; normalized odds
  rows should use the tournament name, for example `Rocket Classic`.
- Make-cut rows are posted as player-specific events with outcomes like `Make`
  and `Miss`; only `Make` is normalized to `make_cut`.
- Round score O/U rows are recognized when the event/market mentions round
  score and the outcome starts with `Over` or `Under`; the numeric line is
  extracted from the outcome text if no explicit line field exists.
- Unmapped markets are excluded by default and can be included with
  `--include-unmapped` for source exploration.
