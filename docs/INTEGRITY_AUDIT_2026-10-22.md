# Integrity Audit — golf_props record, grade pipeline, and headline (2026-10-22)

Scope: the three defect classes audited on the NHL project, applied to this
repository as it stands on `main` at `9c6bec3`:

1. **Headline inflation through pooling** — is the reported performance number
   computed over a superset of the rows the claim implies (retrospective rows,
   excluded players, stale snapshots)?
2. **Dead or documented-but-unused paths** — instructions that point an operator
   at a file or directory that no code writes or reads.
3. **Records that disagree with themselves** — two artifacts claiming to be the
   same record with different contents, or a documented artifact that does not
   exist.

Audit mode: read-only inspection of the working tree, `git log --all`, and the
VM data directory; fixes applied only where the correct behaviour is
unambiguous. Every change is committed separately with the evidence in the
commit message.

Status: complete. Steps 1–4 landed as `cec633a`, `453177c`, `b9a1a77`,
`576e7d8`; §3 is the step-3 inventory, §4 the applied fixes and the verdict,
§5 the evidence index.

---

## 1. Record map

### 1.1 There is no staked record

`golf_props` is forecast-only paper research. It publishes pre-tournament
probabilities; it never recommends wagers or records a position.

- `docs/PRODUCT_CONTRACT.md`: "Status: forecast-only private paper research."
  and "It does not recommend wagers, select positions, size stakes, or claim an
  edge."
- `src/golf_props/notifications/discord.py:1`: "Publish a verified,
  forecast-only golf board to a private Discord channel."
- `src/golf_props/notifications/discord.py:19`: `PROHIBITED_WORDS = ("lock",
  "play", "wager", "bet", "edge")` — enforced on board and alert text at
  lines 168 and 310.
- `grep -rniE "stake|staked|units|pnl|profit|roi_|ledger|bankroll" src/` returns
  only the ops-alert delivery ledger (`notifications/discord.py:256-384`,
  `data/interim/weekly/ops_alerts.json`). No stakes, units, PnL, ROI, or
  bankroll state exists anywhere in `src/`.

Consequence for class 1: there is no staked, unit-denominated headline to
inflate. The analogous number is the **prospective Brier score of graded
journal**, and that is what section 2 recomputes.

### 1.2 The record, precisely

| Role | Path | Writer | Reader | In git |
|------|------|--------|--------|--------|
| Model output, immutable | `data/interim/reports/prospective_forecasts/<event_key>/` (9 files incl. `manifest.json`, `simulation_summary.json`, `top20.csv`…`winner.csv`) | `pipelines/weekly_forecast.py` | `backtest/forecast_archive.py::verify_forecast_archive`, `notifications/discord.py::build_board`, `backtest/forecast_grading.py::grade_forecast` | no (`data/interim/` ignored) |
| Grade record | `data/interim/reports/forecast_grading/<event_key>/` = `graded_predictions.csv`, `metrics.csv`, `report.md`, `grading_manifest.json` | `backtest/forecast_grading.py::grade_forecast` (CLI `grade-forecast`), orchestrated by `pipelines/post_event_grading.py::attempt_post_event_grading` | `report.md`/`metrics.csv` read by humans only; `grading_manifest.json` read for idempotency | Bank of Utah only (force-added) |
| Grade status / idempotency sidecar | `data/interim/weekly/<event_key>/grading.json` | `pipelines/post_event_grading.py` | same module (`reused_existing_output`) | no |
| Incumbent parameters | `data/interim/reports/rolling_round_simulation_validation/frozen_model_manifest.json` | manual freeze (`rolling-simulation-validation`, 2026-08-06) | `pipelines/weekly_forecast.py:113-117` (`WeeklyPaths.manifest`) | no (`data/interim/` ignored); a byte-identical copy is tracked at `data/frozen_model_manifest.json`, which **no code path reads** |
| Rolling retrospective aggregate (reference only) | `data/interim/reports/rolling_recompute_20261007/aggregate_metrics.csv` | `rolling-simulation-validation` run of 2026-10-07 | `post_event_grading._rolling_metrics_path()` fallback; rendered as a "historical reference" column in `report.md` | no (sha pinned in each `grading_manifest.json`) |

Ordering guarantee: `weekly_forecast` writes the archive only after the field is
verified and `pre_start_verified=true` (`docs/PRODUCT_CONTRACT.md`, "Timing");
`grade_forecast` refuses to grade an archive that does not verify, so a grade
cannot exist for an unarchived forecast.

### 1.3 Writers (production surface)

Only two systemd timers run anything:

- `sports-golf-forecast.timer` — every 2 h at :17 — `scripts/linux/run_linux_task.sh
  weekly-forecast` → `python -m golf_props.cli weekly-forecast`. This single
  command both archives forecasts and, once an event finishes, calls
  `attempt_post_event_grading` (manual/loop-driven grading; not a separate unit).
- `sports-golf-bovada.timer` — Mon/Wed/Thu 08:56 → `collect-bovada-golf-odds`
  (odds cross-check only; never feeds the model field and never touches the
  grade record).

The CLI exposes 39 subcommands (`src/golf_props/cli.py:89` `build_parser`,
`main` at line 826); the 37 others are operator tools, backtests, or discovery
helpers. Which of them are reachable from anything other than a human shell is
part of the step-3 inventory.

### 1.4 Consumers

- **Discord** — the pre-event board (`publish-forecast-board` →
  `notifications/discord.py::publish_board`) and ops alerts. No performance
  recap is posted, and no code path reads `metrics.csv`.
- **Dashboard** (`~/dashboard`) — `config/projects.json` sets golf_props
  `run_status`, `reports`, `grade_event`, and `slate` to `null`;
  `dashboard/performance.py:56` budgets 40 rows and `:66` renders the
  placeholder "no grade artifacts". The dashboard therefore shows **no** golf
  headline at all, even though grade artifacts exist on disk (recorded as a
  finding, not fixed here — the dashboard is out of this repository).
- **Humans** — `README.md`, `docs/project_handoff.md`, `docs/NEXT_CHECKIN.md`,
  `docs/continuation_prompt.md`, `docs/research_narrative.md`,
  `docs/PRODUCT_CONTRACT.md`. These documents are the only place a performance
  headline is actually stated, which is why documentation drift is a defect
  class rather than cosmetics.

### 1.5 Headline definition (the number this repo actually claims)

For each event and each target `t ∈ {top20, top10, top5, winner}`:

```
Brier_t = mean over graded players of (p_model(·, t) − 1[player finished in t])²
```

- **Graded player** = appears in both the immutable archive and the final CBS
  leaderboard, matched on canonical player name, minus placement rows whose
  finish is `WD`, `DNS`, or `DQ`.
- `make_cut` is **excluded** from the graded set (it is a cut-prop target, not a
  placement target).
- Late entrants (added after archiving) are ignored; the manifest records
  `intersection_players`, `excluded_players`, and the alias repairs applied.
- `p_model` comes from a 20 000-path frozen simulation. There is no price, no
  stake, and therefore no ROI; "bettable-only analog" here means *restricted to
  rows backed by an artifact*, not *restricted to rows with a market price*.

No cross-event pooling exists in the code; every Brier is per-event. Any
project-level number in the docs is a human aggregation, which is exactly where
class-1 inflation can enter and is what section 2 tests.

---

## 2. Class tests and both headline numbers

### 2.1 What "both ways" means here

The NHL template contrasts an as-reported headline (which pooled rows the board
did not recommend) with a bettable-only recomputation. Golf has no priced
record, so the equivalent contrast is **artifact-backed vs claimed**:

- **As reported** — the prospective record as the documentation states it: three
  graded events, 204 graded players per target (107 Bank of Utah + 68 Baycurrent
  + 29 TOUR, the last at its doc-claimed Brier because no artifact exists).
- **Artifact-verified (bettable-only analog)** — the same average restricted to
  rows whose source artifact exists on disk and verifies: two events, 175 graded
  players per target.

Both are computed from `data/interim/reports/forecast_grading/*/graded_predictions.csv`
(`model_prob` vs `actual`, squared error, unweighted mean per target), with the
single doc-only event contributed at its documented Brier value and count.
Recompute script: `/tmp/recompute_headline.py` (session-local; reproduced below
in the evidence index).

### 2.2 Recomputation (2026-10-22, `main` @ `cec633a`)

Row counts per target per event are equal, so per-event and pooled means use the
same arithmetic.

**top20**

- Bank of Utah Championship 2026 — n=107 — Brier 0.145259
- Baycurrent Classic 2026 — n=68 — Brier 0.201605
- **Artifact-verified pool — n=175 — Brier 0.167154**
- As reported (adds doc-only TOUR Championship, n=29, 0.1967) — n=204 — **0.171354**

**top10**

- Bank of Utah — n=107 — 0.093212
- Baycurrent — n=68 — 0.141556
- **Artifact-verified pool — n=175 — 0.111997**
- As reported — n=204 — **0.125929**

**top5**

- Bank of Utah — n=107 — 0.045155
- Baycurrent — n=68 — 0.101309
- **Artifact-verified pool — n=175 — 0.066975**
- As reported — n=204 — **0.090591**

**winner**

- Bank of Utah — n=107 — 0.009314
- Baycurrent — n=68 — 0.014693
- **Artifact-verified pool — n=175 — 0.011404**
- As reported — n=204 — **0.013294**

Total graded rows on disk: 700 = 175 × 4. (Item 2.5.1 below changes the Bank of
Utah count to 108, after which the pooled numbers become 0.166547 / 0.111469 /
0.066628 / 0.011341 over n=176; both versions are recorded because the audit is
also the evidence for that correction.)

### 2.3 Class (a) — pooling non-recommended rows into the record: NEGATIVE as specified, with one adjacent defect

There is no staked record to contaminate. No stakes, units, PnL, ROI, or
bankroll appear anywhere in `src/`; the only `ledger` symbol is the ops-alert
delivery ledger (`notifications/discord.py:256`), which stores when an alert
was last sent, not money. There is no NO_PLAY / watch / lean / pass flag,
because there is no recommendation layer to produce one:
`PROHIBITED_WORDS = ("lock", "play", "wager", "bet", "edge")` is enforced on
every outgoing board and alert.

Checked specifically:

- **Retrospective rows inside prospective claims:** the rolling aggregate
  (`rolling_recompute_20261007/aggregate_metrics.csv`, 182 events, event dates
  2022-01-06 → 2025-12-11) contains no prospective/Bank/Baycurrent rows; its
  only "TOUR Championship" rows are 2025 historical. README labels the
  `simulation-model-selection`, `rolling-simulation-validation`, and
  `course-challenger-validation` numbers as validation evidence ("encouraging
  performance-model evidence, not a betting-edge result"), and
  `report.md` labels its rolling column "historical reference".
- **Excluded players inside the graded set:** `make_cut` is excluded from
  `graded_targets`, WD/DNS/DQ placement rows are dropped, and the manifest
  records `excluded_players`, `excluded_targets`, `forecast_players_without_results`,
  and `name_aliases_applied`, so the denominator of every Brier is auditable.
- **Cross-event pooling in code:** none. Every Brier is per-event; the 204-row
  average exists only in prose.

The adjacent defect is that the prose pool contains an event with no artifact
(2.5.2). Note the direction: adding that event **raises** every Brier
(0.167154 → 0.171354, 0.111997 → 0.125929, 0.066975 → 0.090591, 0.011404 →
0.013294). This is a provenance defect — the record cannot be reproduced — not
an inflating one.

### 2.4 Class (b) — orphan or frozen writer/reader: POSITIVE (two dead documented paths)

1. **`DEFAULT_ROLLING_METRICS` points at a file that has not existed since the
   2026-10-07 grader rewrite.** `pipelines/post_event_grading.py:47-50` names
   `data/interim/reports/rolling_round_simulation_validation/aggregate_metrics.csv`.
   That directory contains exactly one file, `frozen_model_manifest.json` dated
   2026-08-06. `_rolling_metrics_path()` then silently falls through to the
   newest `rolling_recompute_*/aggregate_metrics.csv`, so the loop works while
   the documented default is fiction — a fail-open mask, not a guard.
2. **The README runbook cannot be executed as printed.** `README.md:331` passes
   that same dead path to `grade-forecast --rolling-metrics`, which is
   `required=True` (`cli.py:286`) and is read through `_read_csv`, which raises
   when the path is missing (`backtest/forecast_grading.py:91`). An operator
   following the documented command gets a hard failure.
3. **`README.md:332` and three docs send the grader output to
   `data/interim/reports/prospective_forecast_grades/<event_key>`**, a directory
   that does not exist, has never existed in `git log --all`, and is not read by
   any code. The live grader writes
   `data/interim/reports/forecast_grading/<event_key>`
   (`post_event_grading.py:43`). Affected: `README.md:332`,
   `docs/project_handoff.md:173` and `:1068`, `docs/NEXT_CHECKIN.md:58`,
   `docs/continuation_prompt.md:97`.
4. **`docs/project_handoff.md:1060-1068`** lists two artifacts as part of the
   evidence set that do not exist: `rolling_round_simulation_validation/report.md`
   (the directory holds only the manifest) and the phantom grade path above.

Provenance is nevertheless intact for the two real grades: each
`grading_manifest.json` pins `rolling_metrics` by SHA-256
(`1140b6aa…` = the current `rolling_recompute_20261007/aggregate_metrics.csv`),
so a reader can still tell exactly which historical aggregate the report column
came from. The defect is the dead pointer, not the data.

### 2.5 Class (c) — two artifacts claiming to be the same record: POSITIVE (three ways)

#### 2.5.1 Duplicate Bank of Utah grade sets with different contents

Two complete, internally consistent grade records exist for the same event,
archive, and leaderboard:

| | canonical (`data/interim/reports/forecast_grading/bank_of_utah_championship_2026/`) | re-grade (`/tmp/bankutah_regrade/`, identical twin `/tmp/grade_hojgaard_check/`) |
|---|---|---|
| created_at_utc | 2026-10-07T03:52:20Z | 2026-10-07T04:17:39Z (twin 04:16) |
| graded_players_per_target | 107 | **108** |
| intersection_players | 111 | **112** |
| excluded_players | 8 | 7 |
| aliases | 9 | 10 (adds `Rasmus Højgaard <-> Rasmus Hojgaard`) |
| top20 Brier | 0.145259 | **0.144474** |
| top10 / top5 / winner | 0.093212 / 0.045155 / 0.009314 | **0.092525 / 0.044792 / 0.009230** |
| results_source.url | CBS Bank of Utah URL | `""` (regrade run without `--results-url`) |

The difference is exactly the o-slash transliteration fix in commit `3e60ce0`
("Hojgaard fix: transliteration fold in `_canonical_name_key`; Bank of Utah
re-grade 108 (was 107)"), which changed `src/golf_props/backtest/forecast_grading.py`
and `tests/test_forecast_grading.py` but **did not touch the tracked artifact**:
`git log --all -- data/interim/reports/forecast_grading/bank_of_utah_championship_2026/metrics.csv`
lists only `7eef471`. `.dashboard/journal.jsonl:6` (2026-10-07) had already named
the gap: "known grader gap: o-slash transliteration (Rasmus Hojgaard) unmatched,
107 graded instead of 108."

So the tracked record is stale, the corrected record lives only in `/tmp`
(ephemeral and absent from git), and running today's code produces the 108
version. Fix applied in step 4 (see 4.1).

#### 2.5.2 A documented grade record that has no artifact anywhere

`docs/project_handoff.md:155-195`, `docs/continuation_prompt.md:91-99`,
`README.md:502-507`, `docs/NEXT_CHECKIN.md`, `docs/research_narrative.md:161-168`,
and `docs/implementation_roadmap.md:488-492` all describe the 2026 TOUR
Championship as archived 2026-08-27, graded 2026-09-01, with Brier
0.1967 / 0.2100 / 0.2331 / 0.0247 over 29 graded players.

Evidence that no such artifact exists:

- `find data -iname "*tour_champ*"` → nothing; `find . -type d -name
  "prospective_forecast_grades"` → nothing.
- `git log --all --oneline -- "data/**tour_championship*"` → empty. The only
  tour-related files ever added under `data/` are the Wyndham field files and
  the Bank of Utah grade.
- The graded record does not exist in this repository's history at the claimed
  date: `src/golf_props/backtest/forecast_grading.py` first appears in commit
  `c3bc4f0` (2026-09-30), twenty-nine days after the claimed 2026-09-01 grade,
  and its first real grade output is `7eef471` (2026-10-07).
- The archive claim is traceable to a Windows host
  (`scripts/windows/run_tour_championship_forecast.cmd`, added in `2ba74c2`,
  writing to `C:\Users\muski\golf_props` and to the legacy one-shot path
  `data\interim\reports\tour_championship_2026_frozen_simulation`, retired by
  `32d3d38`).
- `data/raw/prospective_results/` holds only `bank_of_utah_championship_2026`
  and `baycurrent_classic_2026`; the claimed preserved CBS leaderboard
  `data/raw/prospective_results/tour_championship_2026/` is absent.

Verdict for this item: **doc-claimed, not artifact-verified.** It is not
repairable inside this repo (nothing to repair from), and it is not a
fabrication finding either — the claim is consistent with work done on a host
that is not this VM and whose record was never carried over. It is recorded, and
the documents are corrected in step 4 to stop presenting it as one of the graded
artifacts of record.

#### 2.5.3 Record size stated three ways

- `docs/project_handoff.md` prose implies three prospective events (TOUR,
  Bank of Utah, Baycurrent) and an evidence block listing all three.
- `docs/NEXT_CHECKIN.md:46`: "two graded events is still thin evidence".
- Disk and git: exactly two (`bank_of_utah_championship_2026`,
  `baycurrent_classic_2026`).

#### 2.5.4 Three frozen manifests, two contents

- `data/frozen_model_manifest.json` and
  `data/interim/reports/rolling_round_simulation_validation/frozen_model_manifest.json`
  are byte-identical (SHA-256 `8ee96b9f…`).
- `data/interim/reports/rolling_recompute_20261007/frozen_model_manifest.json`
  (SHA-256 `2614f042…`) differs only in `created_at_utc` (2026-10-07 vs
  2026-08-06) and `prospective_holdout_after` (2026-10-07 vs 2026-08-06); the
  parameters are the same 365-day half-life / 8-round prior / 20 variance-prior
  rounds.

Not a contradiction — same parameters, different freeze timestamps — but three
files claiming to be "the frozen manifest" is exactly the shape that rots.

**Correction to the first draft of this section (2026-10-23, step 3):** the
tracked copy is *not* the one the code reads. `pipelines/weekly_forecast.py:113-117`
hard-codes `data/interim/reports/rolling_round_simulation_validation/frozen_model_manifest.json`
— a path under gitignored `data/interim/`, so **the manifest the production loop
actually loads is not in git**, while the tracked `data/frozen_model_manifest.json`
is read by nothing (`grep -rn frozen_model_manifest src/` returns only the
weekly path, the writer at `rolling_simulation_validation.py:696`, and an
egg-info copy of the README). `docs/project_handoff.md:1065` by contrast points
at the rolling-directory copy, i.e. the document is right and the tracked file
is the orphan. Pinning which copy is canonical — and deciding whether the live
one should be tracked — is a policy call, so this is documented, not changed;
the params are provably equal, so today the split changes nothing about the
forecast. It changes a great deal about reproducibility: see §3.5.

#### 2.5.5 Split source of truth in git

`git ls-files data` = 16 files. Only the Bank of Utah grade artifacts and its
preserved leaderboard are tracked (force-added); `baycurrent_classic_2026`'s
grade and every `data/interim/weekly/*/grading.json` status sidecar exist only on
the VM (`data/interim/` is gitignored). A fresh clone therefore has one grade, a
single host has two, and the audit had to reconstruct the record from VM disk.
Recorded as a finding (step 4 adds no ignore rules — changing what is tracked is
a policy decision).

## 3. Dead code, dead documents, and legacy surface

### 3.1 What "dead" was allowed to mean

Three independent probes, all re-runnable from the repo:

1. **Module reachability** — AST import graph rooted at `golf_props.cli`, so any
   entry point the loop truly uses must be in the reached set.
2. **CLI surface** — every `add_parser` command (`39`) and every
   `add_argument("--…")` flag (`109`) in `src/golf_props/cli.py`,
   cross-referenced against every `*.md`, everything under `scripts/`, and the
   systemd unit files.
3. **Documentation paths** — every repo-relative path appearing in a `.md`
   (`117` distinct), tested for existence on the VM and for presence in
   `git log --all`.

A path that fails probe 3 is only a defect when the sentence around it asserts
the file exists, or hands it to a command a human is meant to run. Template
outputs (`--output-dir <somewhere you choose>`) are not defects, and nothing
below counts them as such.

### 3.2 Modules: none dead

`58` module files under `src/golf_props/`. The import graph from
`golf_props.cli` reaches `46` distinct module names; the residue is package
`__init__` nodes collapsed by the name normaliser, and the unreachable-module
list is empty — printed as an empty set, not inferred.

Four modules look orphaned by name and are not:

- `backtest/simulation_backtest.py` → `simulation-backtest` (documented, README)
- `backtest/value_report.py` → `value-report` (documented, README)
- `odds/covers_inspect.py` → `inspect-covers-odds` (**undocumented**)
- `odds/draftkings_predictions.py` → `run-dk-current-value` (**undocumented**)

Verdict: nothing to delete. The dead surface in this repo sits at the command
layer, and even there "dead" means nobody documented it, not that it cannot run.

### 3.3 CLI commands: 17 of 39 are named in no document and no script

Referenced by no `*.md`, no `scripts/**`, no unit file:

- `doctor`
- `normalize-bootstrap-results`
- `normalize-espn-results`
- `collect-cbs-results`
- `normalize-cbs-results`
- `normalize-manual-odds`
- `build-player-event-features`
- `time-split-baseline`
- `event-rankings`
- `odds-movement`
- `audit-odds-sources`
- `inspect-covers-odds`
- `inspect-odds-url-batch`
- `collect-dk-placement`
- `parse-dk-placement`
- `collect-parse-dk-placement`
- `run-dk-current-value`

These are wired to real modules and would run; they are undocumented, not
broken. Nine belong to the sportsbook cross-check layer that the documents
deliberately demote to "comparison only" (`odds-movement`, `audit-odds-sources`,
`inspect-covers-odds`, `inspect-odds-url-batch`, `normalize-manual-odds`,
`collect-dk-placement`, `parse-dk-placement`, `collect-parse-dk-placement`,
`run-dk-current-value`) — which explains, but does not document, the silence.
The other eight are bootstrap/validation commands for data sources and baselines
the repo has since consolidated or superseded (`doctor`,
`normalize-bootstrap-results`, `normalize-espn-results`, `collect-cbs-results`,
`normalize-cbs-results`, `build-player-event-features`, `time-split-baseline`,
`event-rankings`).

`event-rankings` deserves the footnote: it is the predecessor of the documented
`current-event-rankings`, and a substring search for the former can never
distinguish it from the latter. The first pass of this audit counted 16 dead
commands for exactly that reason and was corrected to 17 by a word-boundary
match. Commands do not go quiet because someone decided to hide them; they go
quiet because the grep says otherwise.

The number that matters: the documented workflow covers 22 of 39 commands. A
reader of `README.md` cannot reproduce the full pipeline, and four orphan-looking
modules survive only because their commands are undiscoverable. Recorded, not
changed — deciding which of the 16 to retire is a product decision, and deleting
CLI surface for undocumented but working code is not an unambiguous fix.

### 3.4 CLI flags: 41 of 109 appear in no document

Most of the 41 belong to the 17 undocumented commands (`--crawl-linked`,
`--max-linked-pages`, `--source-kind`, `--raw-output-dir`, …). The remainder are
optional tuning parameters of documented commands (`--min-group-size`,
`--min-prior-starts`, `--enable-logistic`, `--max-absolute-adjustment`,
`--forecast-due-hours-before`, `--skip-collect`, `--retries`,
`--timeout-seconds`).

No *required* flag of a documented command is undocumented. Checked
mechanically: of 39 `required=True` flags, five appear nowhere in the docs —
`--predictions` (`event-rankings`), `--history-dir` (`odds-movement`), and
`--raw`, `--raw-output-dir`, `--processed-output` (the three `dk-*` commands) —
and all five hang off commands from §3.3. So this is documentation debt, not a
broken runbook.

### 3.5 Documentation paths: 45 of 117 absent, and only 16 are defects

Full accounting, so the number is auditable rather than asserted:

- **4** false positives of the checker: host-absolute prefixes
  (`docs/azure_deployment.md:14` "data/archive", `:18` `…/config/systemd/user`,
  `:124` `…/config/golf_props/env`) and one prose fragment
  (`docs/project_handoff.md:7`, the words "data/source state").
- **23** template output targets of commands that have simply never been run on
  this host (`README.md:169,178,180,195,204,205,237,238,255,260,261,266,287,375,387,446`;
  `docs/continuation_prompt.md:84`; `docs/implementation_roadmap.md:92-96,137`).
- **1** placeholder input inside a command template that also carries
  `"Tournament Name"` / `YYYY-MM-DD` placeholders: `data/raw/fields/current_field.csv`
  (`README.md:236`, again at `:259` and `:286`). The real field files are
  `data/fields/wyndham_championship_2026_field.csv` (+ `_notes.md`, with a second
  copy under `data/raw/fields/`).
- **1** deliverable that the same file then denies: `docs/implementation_roadmap.md:175`
  lists `src/golf_props/backtest/calibration_report.py`, and `:177-179` states
  that no such module exists and calibration output lives in the time-split
  baseline report. Self-corrected, merely untidy.
- **3** **absent inputs: the documented command cannot run as written.**
  `README.md:167` feeds `current-event-rankings --features
  data/interim/features/pga_2001_2026_player_event_features.csv` (absent);
  `README.md:202-203` feeds `audit-course-crosswalk --base
  data/processed/espn_pga_2001_2025 --add data/processed/cbs_pga_2026` and
  `data/processed/` contains only `current_events`, `odds_snapshots`,
  `pga_2001_2026`. Defect, one-shot legacy procedure.
- **4** **dead paths inside live runbooks** — the class (b) finding of §2.4:
  `README.md:331` (superseded `--rolling-metrics` path, command hard-fails),
  `README.md:332`, `docs/NEXT_CHECKIN.md:58`, `docs/continuation_prompt.md:97`
  (all `prospective_forecast_grades/`, a directory that has never existed).
- **6** **artifacts asserted to exist, absent from disk and from all git history**
  (`git log --all -- 'data/**<name>*'` empty for every one):
  `README.md:106-107` (two of the five files in "The latest working Bovada
  collection path produced:" — the two `bovada_golf_current_event_rankings` /
  `_current_value_report` reports), and `docs/project_handoff.md`'s "Important
  Artifacts" list at `:1053` (`performance_data_audit/report.md`), `:1061`
  (`rolling_round_simulation_validation/report.md`), `:1076`/`:1078`
  (`course_challenger_validation/report.md` and `challenger_manifest.json`).
- **2** that are the phantom TOUR record of §2.5.2:
  `docs/project_handoff.md:163` (its archive) and `:171` (its "preserved" CBS
  leaderboard).
- **1** asserted preserved evidence with no copy here:
  `docs/project_handoff.md:193` (`data/raw/current_events/_registry_review/`).

Pattern, stated plainly: the documents were written against a Mac workspace
whose `data/` tree was never carried to this VM (see §2.5.2 for why the records
could not be). This VM's `data/interim/reports/` contains exactly six
directories — `bovada_golf_odds_collection`, `forecast_delivery`,
`forecast_grading`, `prospective_forecasts`, `rolling_recompute_20261007`,
`rolling_round_simulation_validation` — while the documents assert roughly a
dozen research-report paths that the closed-source research runs produced
elsewhere. None of those have ever been in git, so a fresh clone is missing the
same files this host is missing.

### 3.6 Reproducibility from a clone: the production loop cannot run

`pipelines/weekly_forecast.py::WeeklyPaths` fixes the loop's inputs. Checked one
by one against `git ls-files`:

- `data/interim/reports/rolling_round_simulation_validation/frozen_model_manifest.json` — untracked
- `data/interim/features/pga_2001_2026_round_performance.csv` — untracked
- `data/processed/pga_2001_2026` — untracked
- `data/raw/current_events/_schedule` — untracked
- `data/interim/reports/prospective_forecasts` — untracked
- `config/player_aliases.csv` — **tracked**

Five of six are absent from a clone. This is the reproducibility half of
§2.5.5 and the reason the §3.5 correction matters: the tracked
`data/frozen_model_manifest.json` is the one artefact of the six that a clone
*does* have, and no code reads it. Recorded, not changed — adding data to git
(or a provisioning script) is a policy decision with storage consequences, and
the audit's mandate is to apply only unambiguous fixes.

### 3.7 Legacy surface that is correctly retired, and correctly documented

Checked so that "legacy" is not assumed:

- `--allow-retrospective` is **documented**, not an undocumented escape hatch:
  `README.md:297`, `docs/project_handoff.md:707,985`,
  `docs/research_narrative.md:119,278`. It is also enforced in code —
  `pipelines/current_event_simulation.py:161` refuses a non-prospective event
  unless the flag is set, and the run is labelled `retrospective_replay`.
  No defect.
- `scripts/windows/run_weekly_forecast.cmd`, `scripts/windows/run_bovada_collect.cmd`
  and `docs/windows_deployment.md` describe the retired
  `C:\Users\muski\golf_props` host (§2.5.2). They are marked as Windows
  deployment docs and are not invoked by anything on this host: the only
  installed units are `sports-golf-forecast.timer`/`.service` and
  `sports-golf-bovada.timer`, which call `scripts/linux/run_linux_task.sh`.
  No defect, but they are the origin of several of the §3.5 assertions.
- `docs/azure_deployment.md` still calls the Mac the durable workspace
  (`:12-13`) while the deployment it documents is this VM. Stale by
  supersession, not contradiction; folded into step 4's doc corrections.

### 3.8 What this section does not claim

- It does not claim any module, command, or flag is unreachable — that was
  tested and came back negative.
- It does not claim the 23 template paths or the 41 undocumented flags are
  defects.
- It does not claim the documented runbooks other than `README.md:331` were
  executed. Only that one was run end-to-end, because only that one hands the
  reader a path the code itself defaults to and the file is provably gone.

---

## 4. Fixes applied (step 4)

Scope rule for this section: a fix was applied only where the correct value is
determined by the code itself or by re-running a documented command. Anything
that needs a decision — which of 17 undocumented commands to retire, which data
belongs in git, what to do with a record whose source no longer exists — is
documented in §2.5 and §3 and left alone. Steps 1–3 are commits `cec633a`,
`453177c`, `b9a1a77`; step 4 is commit `576e7d8`.

### 4.1 The Bank of Utah grade: 107 graded players rewritten to 108

**Cause, from git alone.** Commit `3e60ce0` (2026-10-07T04:18) added the
transliteration fold to `_canonical_name_key` and its message reads "Hojgaard
fix: transliteration fold in `_canonical_name_key`; Bank of Utah re-grade 108
(was 107), 232 tests pass". `git show --stat 3e60ce0` touches `src/`, `tests/`
and `.dashboard/` — not one artifact. `git log -- data/interim/reports/forecast_grading/bank_of_utah_championship_2026/`
returns only `7eef471` (03:52, twenty-five minutes *before* the fix). The
re-grade happened on disk and was never committed, so the record that the
repository states is the pre-fix one: 107 graded of 115 forecast players, with
`Rasmus Højgaard` in `forecast_players_without_results` and `Rasmus Hojgaard` in
`ungraded_results_players` — the same golfer on both sides of a name it could
not fold.

**Inputs did not change.** The old and new `grading_manifest.json` carry
identical `input_sha256` blocks for the archive and the preserved CBS page. The
entire manifest difference is the consequence of the fold:

- `name_aliases_applied` gains the `Højgaard`/`Hojgaard` pair (10 aliases total);
- `intersection_players` 111 → 112;
- `graded_players_per_target` 107 → 108 for all four targets;
- `forecast_players_without_results` drops `Rasmus Højgaard` (8 → 7).

`model_prob` is unchanged for every one of the 428 previously graded rows; what
moves is the field denominator in `baseline_prob` (20/107 → 20/108, 10/107 →
10/108, 5/107 → 5/108, 1/107 → 1/108) and the four added `Højgaard` rows.

**Reproduced independently, twice.** The Oct-7 04:17 re-grade had survived on
this host in `/tmp/bankutah_regrade`; the step-4 re-run is
`/tmp/bu_r1`, generated with the same arguments into an empty directory
(`--results-url` included, matching the producer of the committed 03:52 file,
whose manifest records the URL):

```
cd ~/golf_props && PYTHONPATH=src .venv/bin/python -m golf_props.cli grade-forecast \
  --archive-dir data/interim/reports/prospective_forecasts/bank_of_utah_championship_2026 \
  --results-page data/raw/prospective_results/bank_of_utah_championship_2026/cbs_final_leaderboard.html \
  --rolling-metrics data/interim/reports/rolling_recompute_20261007/aggregate_metrics.csv \
  --output-dir /tmp/bu_r1 \
  --results-url https://www.cbssports.com/golf/leaderboard/pga-tour/31000135/bank-of-utah-championship/
```

`sort graded_predictions.csv | diff` between the Oct-7 and Oct-23 runs: empty.
`diff metrics.csv`: empty. The 108-row content is reproducible; only the
timestamp differs.

**Adjacent defect, documented and not fixed: row order is not reproducible.**
Two back-to-back runs (`/tmp/bu_r1`, `/tmp/bu_r2`) produce `graded_predictions.csv`
files that differ as written and are byte-identical once sorted, while
`metrics.csv` is byte-identical either way. The metric is a mean, so the grade
is unaffected; the record is not diffable between runs, which is what makes a
stale-vs-fresh artifact look like a large rewrite (`860` changed lines in the
step-4 diff for what is four added rows and one rounding denominator). Not fixed
here: making the writer sort its output changes a shared artifact format for
every event, and the audit's mandate is unambiguous repairs only. Recorded as a
reproducibility finding.

**Write.** `grade-forecast` refuses a non-empty output directory, so the record
was produced empty-dir-first and then copied over the tracked files. Old bytes
are recoverable at `7eef471`:

- `graded_predictions.csv` `c5b365bb1be3aaf20050c87e3b923e4402083e37c34054834e18a1d0431427e2`
  → `3cdc62b390077ffd5714241b866c50987c252a9672ba4b6a1c23b5a76afda55e`
- `metrics.csv` `2cc3b6e6aff6723f92c9c81d0cc062c4441208fedb8f239eb134c7bee0aff10a`
  → `47adb17163598897bf26477eef2c421fdcc0aa6490cc3bb816bdd84fd056b1d8`
- `report.md` `cf18350ed0b1be8beb4a897169893087640370c4a713fb7bc94af382bbf69d4e`
  → `cf453ebfe0b8fb407bdbc1115e8423080b7704515d753ac47ff40fc53e798da0`
- `grading_manifest.json` `63d3c01e5443dd5dea2c009832ee75557c65c311d94c522d4756d9969fbd2a64`
  → `a48f33469d904a5fc4e5f62bea3f99c14de6289df6450f5bef2c16238801c604`

**Per-event effect.** Bank of Utah `top20` Brier 0.145259 → 0.144474,
`top10` 0.093212 → 0.092525, `top5` 0.045155 → 0.044792, `winner` 0.009314 →
0.00923. Baseline Brier moves the same way, so `brier_improvement` stays
essentially unchanged (+0.000867 → +0.000588 on `top20`; the fold adds a player
the model liked more than the field average).

**Headline effect** (see §2.2 for the definition and the three versions):

- before, artifact-verified, n=175: 0.167154 / 0.111997 / 0.066975 / 0.011404
- after, n=176: 0.166547 / 0.111469 / 0.066628 / 0.011341

Every target improves by a few ten-thousandths. The direction is not the point;
the point is that the number the repository advertises is now the number its own
artifact produces when the documented command is run against it.

### 4.2 Dead rolling-metrics reference in the live grading loop

`pipelines/post_event_grading.py` carried `DEFAULT_ROLLING_METRICS =
data/interim/reports/rolling_round_simulation_validation/aggregate_metrics.csv`,
a file that has never existed on this host or in git (the directory exists and
holds `frozen_model_manifest.json` and a `report.md` from the retired Mac
workspace — nothing named `aggregate_metrics.csv`). It was dead only because a
glob fallback happened to find
`rolling_recompute_20261007/aggregate_metrics.csv`, so the loop worked while
naming a file it does not read.

Changed: the literal is gone; `ROLLING_RECOMPUTE_GLOB =
"rolling_recompute_*/aggregate_metrics.csv"` names the actual contract, the
fallback list is one entry shorter, and `_rolling_metrics_path()` says what it
does (prefer `$GOLF_PROPS_ROLLING_METRICS`, else the newest recompute directory,
else `None`). Grep after the change: `DEFAULT_ROLLING_METRICS` appears in no
module, test, or script; the only surviving mention of the dead path is the
comment that records why it is dead. Resolved value on this host:

```
rolling_recompute_*/aggregate_metrics.csv
/home/azureuser/golf_props/data/interim/reports/rolling_recompute_20261007/aggregate_metrics.csv (exists)
```

### 4.3 Nine dead paths in live runbooks corrected

Docs only, no behaviour, every replacement checked against the filesystem:

- `README.md:331-332` — the `grade-forecast` example now passes
  `--rolling-metrics data/interim/reports/rolling_recompute_20261007/aggregate_metrics.csv`
  and writes `--output-dir data/interim/reports/forecast_grading/<event_key>`,
  with a paragraph stating that the weekly loop resolves the newest recompute
  directory itself and that `GRADING_ROOT` is the grade root. This is the one
  documented command in §3.5 that hard-failed; it now runs and reproduces the
  committed artifact (see §4.5).
- `docs/NEXT_CHECKIN.md:58` — `prospective_forecast_grades/` →
  `forecast_grading/bank_of_utah_championship_2026/`.
- `docs/continuation_prompt.md:97` — says the TOUR grade came from the retired
  Mac workspace, that no copy exists here, and points at
  `forecast_grading/<event_key>` for the two that do.
- `docs/project_handoff.md:173` — grade artifacts → "none in the repository"
  with the citation to §2.5.2; `:1053` performance audit → never in git,
  regenerate with `audit-performance-data`; `:1061` rolling report →
  `rolling_recompute_20261007/report.md`; `:1068` "first prospective grade" →
  the two real `forecast_grading/` directories; `:1076`/`:1078` course
  challenger report and manifest → never in git, regenerate.

### 4.4 Deliberately not changed

- **The TOUR record** (§2.5.2). No artifact, no archive, no leaderboard page, no
  git history. Reconstructing it would mean inventing a result; the documents now
  say it does not exist here.
- **The 17 undocumented commands and 41 undocumented flags** (§3.3, §3.4).
  Retiring or documenting them is a product decision, not a correction.
- **The remaining seven §3.5 paths** that are not in a live runbook: the three
  absent-input commands (`README.md:167`, `:202-203`), the two Bovada reports
  (`README.md:106-107`), `_registry_review/` (`docs/project_handoff.md:193`),
  and `implementation_roadmap.md:175` (already self-corrected two lines later).
  Each needs a decision about whether the workflow or the claim is the wrong
  one, and two of them are one-shot legacy procedures that were never part of
  the loop.
- **The dashboard's null golf headline** (§1.4). The dashboard is outside this
  repository.
- **The three frozen manifests** (§2.5.4) and **the untracked production
  inputs** (§3.6). Adding data to git, or pointing the tracked
  `data/frozen_model_manifest.json` at something, is a policy decision with
  storage consequences; the audit records which file is live and which is read
  by nothing.
- **Row order in `graded_predictions.csv`** (§4.1) and the **silent fall-through
  when `$GOLF_PROPS_ROLLING_METRICS` points at a missing file** — the override is
  preferred but only if it exists, so a typo quietly grades against the newest
  recompute directory. Both are pre-existing behaviour, both are recorded here,
  neither is repaired by a change whose correctness is self-evident.

### 4.5 Verification of step 4

- `.venv/bin/python -m pytest -q` → `264 passed` (read from the summary line, not
  from the exit status). No test asserted the removed constant.
- Headline recomputation over `data/interim/reports/forecast_grading/*` (script
  in §5.1) → `bank_of_utah_championship_2026` 432 rows,
  `baycurrent_classic_2026` 272 rows, n=176 per target, 0.166547 / 0.111469 /
  0.066628 / 0.011341.
- The literal README command, run against the corrected path into an empty
  scratch directory, produces a `metrics.csv` byte-identical to the committed
  one and a `graded_predictions.csv` identical as a set: the documentation and
  the artifact now agree.
- Consumers of the rewritten artifact: `grep -rn "graded_predictions.csv"` over
  `src/ scripts/ deploy/` returns the writer (`pipelines/post_event_grading.py`
  comment, `backtest/forecast_grading.py:391`) and nothing that reads it — it is
  a record, not an input.
- `grep -rn "prospective_forecast_grades"` over the repository, excluding this
  document: no matches. `grep -rn "rolling_round_simulation_validation/aggregate_metrics"`
  → the one explanatory comment in §4.2.
- `git status -s` after the commit: only `.dashboard/checkpoint.json` and
  `.dashboard/journal.jsonl`, dirty since the 2026-10-13 loop writes and
  deliberately left out of every commit in this audit (§5.3).

### 4.6 Verdict

**The three defect classes, answered:**

1. **Inflation / "bettable-only analog"** — **negative as specified**. No stake,
   units, or PnL anywhere; no `NO_PLAY` layer; `PROHIBITED_WORDS` is enforced on
   outbound copy; no code path pools Brier across events. The one adjacency is
   provenance, not arithmetic: the prose headline pooled a third event that has
   no artifact anywhere, and including it made every number worse, not better
   (§2.2). A defect of record-keeping that happens to point the wrong way is
   still a defect of record-keeping.
2. **Dead code / dead path in the live loop** — **positive**. A constant naming a
   file that never existed, kept alive by a glob fallback; a README command that
   could not run; four documents pointing at a `prospective_forecast_grades/`
   root that has never existed. Fixed in §4.2 and §4.3.
3. **Documentation asserting artifacts that are not there** — **positive, five
   ways**: a 107-row grade against a corrected 108; a TOUR grade with no artifact
   anywhere; one record described at three different sizes; three frozen
   manifests with two contents and two sources of truth; and the stale grade
   itself, left behind by a commit whose message claims the re-grade. Two of
   these are corrected here — the 107/108 record (§4.1, which is also the stale
   grade) and the size statements that disagreed with it (§4.3). The TOUR record
   is documented as unrecoverable (§2.5.2), and the frozen-manifest split and
   the tracked-but-unread manifest are documented in §2.5.4 and §3.6, because
   repairing either means choosing which file becomes the source of truth.

**What the audit does not claim.** It does not claim the model is well
calibrated (§2.2's numbers are *worse* than the 0.1307 rolling reference on every
target), nor that the documented pipeline is reproducible from a clone (it is
not, §3.6), nor that the micro-edits to `README.md` make the 23 template paths
real. It claims that every number this repository states about itself is now
either produced by the command that the repository documents, or labelled as
absent.

---

## 5. Evidence index

Every claim above resolves to one of these commands. Paths are relative to
`~/golf_props` on the audit host; `.venv/bin/python` is the repo interpreter.

### 5.1 Headline recomputation (§2.2, §4.1)

```python
# /tmp/headline.py — mean squared error of model_prob against actual, per target
import csv, glob, os, collections
rows = collections.defaultdict(list)
for p in sorted(glob.glob('data/interim/reports/forecast_grading/*/graded_predictions.csv')):
    ev = os.path.basename(os.path.dirname(p)); n = 0
    with open(p) as f:
        for r in csv.DictReader(f):
            rows[r['target']].append((float(r['model_prob']) - float(r['actual'])) ** 2); n += 1
    print('event', ev, 'rows', n)
for t in ('top20', 'top10', 'top5', 'winner'):
    v = rows[t]; print(t, 'n=%d' % len(v), '%.6f' % (sum(v) / len(v)))
```

Result, before the §4.1 rewrite (n=175): `top20 0.167154  top10 0.111997
top5 0.066975  winner 0.011404`. After (n=176): `top20 0.166547  top10 0.111469
top5 0.066628  winner 0.011341`. The "as reported" 0.171354 / 0.125929 / 0.090591
/ 0.013294 is the same computation with the doc-only TOUR event's stated numbers
folded in as a third sample; there is no artifact to recompute it from.

### 5.2 Grading record archaeology (§2.5.1, §4.1)

```
git log --oneline -- data/interim/reports/forecast_grading/bank_of_utah_championship_2026/
  -> 7eef471 only (03:52, before the alias fix)
git show --stat 3e60ce0        # message claims "Bank of Utah re-grade 108 (was 107)"
  -> src/, tests/, .dashboard/ — no artifact
diff <(git show 7eef471:.../grading_manifest.json) .../grading_manifest.json
  -> alias applied, intersection 111->112, graded 107->108, inputs identical
```

### 5.3 Working-tree hygiene

```
git status -s
 M .dashboard/checkpoint.json
 M .dashboard/journal.jsonl
```

Both were dirty before step 1 (the 2026-10-13 loop wrote an ESPN withdrawal
checkpoint and journal line). They are not part of this audit, they carry no
headline this audit published, and no commit in steps 1–4 touches them:
`git show --stat cec633a 453177c b9a1a77 576e7d8` lists no `.dashboard/` path.

### 5.4 Reachability and documentation inventory (§3.1–§3.5)

| Check | Command | Result |
| --- | --- | --- |
| Unreachable modules | import graph from `golf_props.cli` | none unreachable |
| Undocumented commands | parser `add_parser` names vs `README.md` + `docs/**` (word-boundary) | 17 of 39 undocumented |
| Undocumented flags | parser flags vs docs | 41 of 109 |
| Required flags undocumented | `required=True` subset | 5 of 39, all on undocumented commands |
| Documented paths absent | every `data/...` or `src/...` token in docs, checked on disk | 45 of 117 absent, 16 defects |
| Clone reproducibility | `git ls-files` vs `WeeklyPaths` inputs | 5 of 6 untracked |

### 5.5 Fix verification (§4.2–§4.5)

```
.venv/bin/python -m pytest -q                      -> 264 passed
python /tmp/chk_rolling2.py                        -> ROLLING_RECOMPUTE_GLOB resolves,
                                                      data/interim/reports/rolling_recompute_20261007/aggregate_metrics.csv exists
bash /tmp/readme_check.sh                          -> README_CMD_MATCHES_COMMITTED_ARTIFACT
                                                      METRICS_IDENTICAL
grep -rn DEFAULT_ROLLING_METRICS src/ tests/ scripts/   -> 0
grep -rn prospective_forecast_grades . (excl. this doc)  -> 0
grep -rn graded_predictions.csv src/ scripts/ deploy/    -> writer only, no reader
```

`/tmp/readme_check.sh` runs the §4.3 README command verbatim with the Bank of
Utah arguments into an empty directory, then compares sorted
`graded_predictions.csv` and raw `metrics.csv` against the committed artifact.

### 5.6 Commits

```
cec633a  step 1 — class tests and both headline numbers (§2)
453177c  step 2 — class (a)/(b)/(c) findings and the artefact map (§1, §2.3–§2.5)
b9a1a77  step 3 — dead-code, dead-doc and legacy-surface inventory (§3)
576e7d8  step 4 — fixes: rolling-metrics constant, nine doc paths, 108-player
                   Bank of Utah record (§4)
```

All four are on `main` and pushed to `origin/main`. Nothing was published
anywhere else.
