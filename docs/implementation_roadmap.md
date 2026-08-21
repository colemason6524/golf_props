# Implementation Roadmap

Date: 2026-07-16

Last updated: 2026-08-10

## North Star

Build a PGA golf props research engine that can:

1. collect historical player/event/course results,
2. collect automated sportsbook odds snapshots without manual entry,
3. build leakage-safe player/course/form features,
4. estimate probabilities for core props,
5. compare those probabilities to market prices,
6. backtest results honestly over time.

The first goal is not a fancy model. The first goal is a trustworthy data
pipeline that can tell us when a model is actually learning something.

## Phase 0: Repo Scaffold

Purpose: turn this from docs-only into a runnable Python research project.

Deliverables:

- `pyproject.toml`
- `src/golf_props/`
- `tests/`
- `data/raw/`, `data/processed/`, `data/interim/`
- `logs/`
- basic CLI entry point
- pytest smoke test

Status: implemented.

Initial dependencies:

- `pandas`
- `numpy`
- `scikit-learn`
- `beautifulsoup4`
- `requests`
- `pytest`

Avoid at first:

- browser automation
- paid APIs
- database servers
- model complexity

## Phase 1: Historical Results Bootstrap

Purpose: get event/player/result history into canonical tables.

Primary source candidates:

- Kaggle PGA Tour Results 2001-Dec 2025
- Kaggle / Advanced Sports Analytics PGA 2015-2022

Deliverables:

- raw CSV ingestion path
- source-specific parser
- canonical normalizer for:
  - `events`
  - `courses`
  - `players`
  - `event_courses`
  - `player_event_results`
  - `round_scores` if available
- data quality report

Status: implemented for the bootstrap/ESPN-style historical dataset, CBS 2026
collection/normalization, merge flow, and an auditable reviewed cross-source
course identity crosswalk.

Validation checks:

- every player result maps to one event
- event dates parse cleanly
- course names are present where available
- finish positions normalize into numeric/text values
- made-cut labels are derivable or explicitly missing
- top-20/top-10/top-5 labels match finish positions
- withdrawals/disqualifications are not treated as ordinary missed cuts

First useful output:

```text
data/processed/bootstrap/events.csv
data/processed/bootstrap/courses.csv
data/processed/bootstrap/players.csv
data/processed/bootstrap/player_event_results.csv
data/processed/bootstrap/round_scores.csv
```

## Phase 2: Feature Builder V1

Purpose: build leakage-safe player-event features from historical results.

Feature groups:

- recent form
- course history
- event/course context
- field strength proxy

V1 features:

- prior starts
- days since last start
- rolling made-cut rate
- rolling top-20 rate
- rolling top-10 rate
- rolling average finish
- rolling average score to par when available
- course starts
- course made-cut rate
- course top-20 rate
- course average finish
- season-to-date starts
- season-to-date made-cut rate
- field size
- field average/rank proxy when rankings are available

Leakage rule:

For a player in event `E`, use only events completed before `E` starts. Never
allow current-event results, round stats, or final standings into pre-event
features.

Deliverables:

- `src/golf_props/features/player_event.py`
- `data/interim/features/player_event_features.csv`
- feature data quality report
- tests with tiny fixtures that prove current-event leakage is blocked

Status: implemented. The current main feature file is
`data/interim/features/pga_2001_2026_player_event_features.csv`.

## Phase 3: First Labels and Baselines

Purpose: create predictable targets and measure simple models before odds.

Targets:

- `make_cut`
- `top20`
- `top10`
- `top5`
- `winner`

Baselines:

- historical base rate
- player rolling-rate baseline
- logistic regression
- gradient boosting only after logistic baseline is stable

Metrics:

- Brier score
- log loss
- calibration buckets
- rank correlation within events
- top-N hit rates
- time-split validation by event date

Deliverables:

- `src/golf_props/models/time_split_baseline.py`
- `src/golf_props/backtest/calibration_report.py`
- reports under `data/interim/reports/`

Status: implemented for time-split baseline reports and current-event ranking
reports. `calibration_report.py` is not a separate module; calibration-style
outputs live in the time-split baseline report path.

Pass condition:

The pipeline can train on earlier events, test on later events, and produce
calibrated probabilities without using market prices.

## Phase 4: Odds Snapshot Archive

Purpose: start collecting the rarest asset: timestamped sportsbook prices.

Original preferred order:

1. FanDuel
2. DraftKings

Current practical order after source debugging:

1. Bovada
2. DraftKings Predictions as a stale/fallback placement source only when it
   still parses
3. FanDuel/DraftKings sportsbook pages as future targets once a stable
   no-browser route is found

Markets to collect first:

- make cut
- top 20
- top 10
- top 5
- first-round leader / round leader where available
- tournament head-to-head
- outright winner as reference
- round score over/under when posted

Collection rule:

Store raw responses/pages first. Parse second. Raw data is the research asset.

Deliverables:

- raw snapshot metadata format
- source URL registry
- manual snapshot import path
- later: automated collector if pages are accessible
- parser for visible odds data when feasible
- normalized `odds_snapshots.csv`

Status: partially implemented and usable through Bovada.

Implemented:

- `src/golf_props/odds/bovada.py`
- CLI command `collect-bovada-golf-odds`
- raw JSON archive at `data/raw/odds_snapshots/bovada_golf_latest.json`
- normalized latest snapshot at
  `data/processed/odds_snapshots/bovada_golf_latest.csv`
- collection report at
  `data/interim/reports/bovada_golf_odds_collection/report.md`

Important debugging lesson:

- DraftKings sportsbook JavaScript bundles revealed backend route families under
  `sportsbook-nash.draftkings.com`, but direct no-browser requests were blocked
  by Akamai. Do not assume DraftKings sportsbook is solved just because endpoint
  strings are visible in bundles.
- DraftKings Predictions previously parsed placement markets for The Open, but
  current collection became unreliable because odds content moved behind linked
  or asynchronous pages. Existing DK reports should be treated as stale samples,
  not proof that current DK live odds are working.
- Bovada pages render as a JavaScript shell, but their app uses a public JSON
  service route:
  `https://www.bovada.lv/services/sports/event/coupon/events/A/description/golf/pga-tour`.
  This endpoint returned current PGA market JSON without browser automation.

Snapshot cadence:

- Monday after markets open
- Tuesday after field/tee-time movement
- Wednesday evening
- Thursday pre-start
- between rounds when round markets are available
- final closing proxy before each relevant market starts

Design tradeoff:

The current collector writes a "latest" snapshot and raw payload. It does not
yet automatically append timestamped history on every run. That should be added
before using line movement as a serious signal.

Validation checks:

- sportsbook present
- market type present
- player/selection present
- American/decimal price parseable
- captured timestamp present
- event matched to canonical event
- duplicate snapshots handled without data loss

## Phase 5: Market Baseline and Value Backtest

Purpose: compare model probabilities to market-implied probabilities.

Markets:

- make cut
- top 20
- top 10
- top 5
- winner
- head-to-head

Core calculations:

- American odds to implied probability
- sportsbook hold / no-vig approximation where possible
- `edge = model_prob - market_prob`
- expected value estimate
- closing-line movement

Reports:

- market coverage by event/book/market
- model vs market calibration
- value candidate list
- candidate backtest by threshold
- closing-line value report

Important rule:

Do not claim betting edge until we have enough out-of-sample events and stable
odds coverage. Early reports should be labeled exploratory.

Status: implemented for current-event value reporting using existing
probability rankings plus Bovada winner/top-N/make-cut odds. The current command
flow is:

```bash
PYTHONPATH=src python3 -m golf_props.cli collect-bovada-golf-odds

PYTHONPATH=src python3 -m golf_props.cli current-event-rankings \
  --features data/interim/features/pga_2001_2026_player_event_features.csv \
  --odds data/processed/odds_snapshots/bovada_golf_latest.csv \
  --output-dir data/interim/reports/bovada_golf_current_event_rankings \
  --event-date YYYY-MM-DD \
  --top-n 25

PYTHONPATH=src python3 -m golf_props.cli value-report \
  --rankings data/interim/reports/bovada_golf_current_event_rankings/event_rankings.csv \
  --odds data/processed/odds_snapshots/bovada_golf_latest.csv \
  --output-dir data/interim/reports/bovada_golf_current_value_report \
  --top-n 50
```

The current reports are pre-tournament snapshots. Live tournament state is not
part of the current value pipeline.

## Phase 6: Course Fit and Stat Enrichment

Status note (2026-08-10): partially started, not complete. Cross-source course
identity repair and a same-course residual challenger were implemented and
evaluated; the challenger was not promoted. Richer course profiles,
strokes-gained/stat enrichment, and true course-fit modeling have not started.

Purpose: move beyond simple course history into why a player may fit a course.

Candidate sources:

- GolfStats export if purchased
- PGA Tour stat pages if usable
- public results datasets if they include traditional stats
- Data Golf only if we decide paid/API acceleration is worth it later

Features:

- par-3/par-4/par-5 scoring fit
- birdie/bogey tendency
- GIR
- fairways hit
- driving distance
- driving accuracy
- scrambling
- putting
- SG categories where available
- course yardage/par profile
- hole-level scoring difficulty when available

Deliverables:

- `course_profiles.csv`
- `player_stat_profiles.csv`
- `course_fit_features.csv`
- ablation report showing whether course-fit features add signal

## Phase 7: Weather, Tee Waves, and Round Props

Purpose: support the more granular golf props the user cares about.

Markets:

- round score
- birdies or better
- bogeys or worse
- greens in regulation
- fairways hit
- pars

Required data:

- round tee times
- observed/forecast weather
- hole par/yardage
- round/hole stat results
- sportsbook round lines

Deliverables:

- weather snapshot collector/importer
- tee-time importer
- round-level feature builder
- round-prop grading rules
- round-prop backtest reports

## Phase 8: Live Weekly Workflow

Purpose: make this operational during PGA weeks.

Weekly flow:

1. Create/update event record.
2. Import field list.
3. Build pre-event features.
4. Collect Monday odds.
5. Produce first value report.
6. Refresh after tee times/withdrawals.
7. Collect Wednesday/Thursday closing snapshots.
8. Finalize after event results.
9. Grade markets.
10. Append event to training history.

Reports:

- current week model probabilities
- sportsbook market comparison
- value candidates
- data quality warnings
- post-event grading summary

## First Two-Week Build Plan

### Week 1

- Create Python scaffold.
- Add fixture-based tests.
- Download/import first public results dataset manually.
- Normalize events, players, courses, and results.
- Build make-cut/top-N labels.
- Build first data quality report.

### Week 2

- Build leakage-safe feature table.
- Train time-split baseline for make-cut/top-20/top-10.
- Add odds snapshot schema.
- Add manual odds normalization as a fallback/test fixture path.
- Add Bovada no-browser collection for current PGA odds.
- Produce first exploratory model-vs-market report.

## Current State and Immediate Next Action

The authoritative current-state and continuity record is
`docs/project_handoff.md`. The research story and outward risks are in
`docs/research_narrative.md`. The copy-ready takeover prompt is
`docs/continuation_prompt.md`.

Progress framing: advanced on the performance-model foundation; early on
prospective validation and market-edge research. Do not describe the project as
literally halfway through.

The auditable cross-source course identity crosswalk is implemented. It uses
review-only exact normalized/token proposals and applies only explicitly
accepted mappings. The reviewed file maps 29 CBS identities and consolidates
two same-venue ESPN identities; `Pete Dye Stadium Course PGA West` remains
unresolved because no safe historical identity exists.

Canonical and round-performance data were regenerated, the incumbent was
revalidated unchanged, and latest-window matched-course player coverage rose
from 0% to 62.9886%. The paired challenger still did not earn promotion: the
2025 fold selected zero effect and bootstrap intervals crossed zero for
top-20 through winner.

The frozen 365/8/20 simulator is now wired into a reproducible
`predict-current-event` workflow. It verifies the frozen input hashes, locks
the manifest parameters, enforces strict as-of/prospective rules, reports field
identity warnings, and writes a hashed performance-only forecast bundle.

A Wyndham Championship 2026 dry-run was archived as
`retrospective_replay` because its start date equals the prospective
threshold. It is not prospective evidence.

The immediate next operational task is still the first genuinely prospective
forecast for an event starting after 2026-08-06, but only under honest event-
structure assumptions. FedEx St. Jude (2026-08-13) is date-eligible and
calendar-next, yet it is a no-cut playoff event that conflicts with the
ordinary top-65-and-ties cut assumption. Resolve that explicitly before
running, or wait for the next ordinary full-field cut event. Preserve any
valid prospective run unchanged for later grading. Sportsbook comparison
remains a separate later layer and must not turn structural-baseline evidence
into a betting-edge claim.

The original performance-first modeling priorities were:

1. point-in-time current-event features built from an independent field,
2. event-relative round-performance baselines,
3. a field-level tournament simulator for coherent placement probabilities,
4. strict walk-forward calibration and ranking evaluation,
5. performance-only weekly reports with uncertainty and data-quality warnings.

Items 1–4 and the canonical performance-data audit are implemented. Item 5 is
partially represented by simulation reports but is not yet an integrated weekly
workflow. Bovada timestamp history remains valuable because prices are
perishable, but it should not block the course identity repair.

Performance-model implementation update:

- event-round-relative performance rows are implemented
- implausible partial/corrupt round scores are filtered and reported
- recency-weighted player strength with mean/variance shrinkage is implemented
- seeded field-level simulation with a top-65-and-ties cut is implemented
- performance-only make-cut/top-N/winner probabilities are implemented
- walk-forward comparison against structural field baselines is implemented
- reusable point-in-time round-history indexing is implemented for repeated
  walk-forward experiments
- validation-only decay/shrinkage selection with a disjoint later test window
  is implemented
- four-fold rolling-origin evaluation, equal-event bootstrap intervals,
  equal-frequency calibration diagnostics, and a frozen future-model manifest
  are implemented
- manifest-driven current-event strength and joint-field simulation are
  implemented with hash verification and explicit prospective classification

The first full-data smoke backtest used five recent events and 1,000 simulations
per event. A subsequent selection run compared nine configurations over 20
validation events from 2024–2025 and evaluated the selected configuration once
over 10 later 2026 events. The selected 180-day half-life and 8-round mean prior
improved Brier score versus the structural baseline for make-cut (+0.0166),
top-20 (+0.0137), top-10 (+0.0040), and top-5 (+0.0016); winner was essentially
flat (-0.00004). These are performance-model results, not evidence of a betting
edge. That one split motivated the broader rolling-origin evaluation below.

Rolling-origin implementation update:

- four folds independently selected on 2021, 2022, 2023, and 2024 data, then
  evaluated on the following season
- all four folds selected a 365-day half-life, 8-round mean prior, and 20-round
  variance prior
- 182 evaluation tournaments produced positive Brier improvement in every fold
  for make-cut, top-20, top-10, top-5, and winner
- equal-event 95% bootstrap intervals excluded zero for make-cut through top-5
- calibration ECE ranged from 0.0086 for top-5 to 0.0260 for make-cut;
  calibration slopes above 1 indicate probabilities are somewhat compressed
- a separately selected future configuration is frozen with input hashes, a
  `source_data_through` cutoff, and a freeze timestamp; only events starting
  after both qualify as prospective holdout evidence

The same-course residual challenger was rerun after repairing cross-source
course identity. It still produced only a +0.00015 aggregate make-cut Brier
improvement; paired event intervals crossed zero for top-20, top-10, top-5,
and winner. The 2025 fold selected course weight 0. The latest freeze window,
now with 62.9886% matched-course player coverage, selected weight 0.5 and a
40-round course prior, but this isolated selection does not overcome the
unstable paired evidence. The incumbent remains unchanged.

The repo should not wait for perfect data. It should be designed so every new
source can be inspected, normalized, validated, and compared without changing
the modeling code.
