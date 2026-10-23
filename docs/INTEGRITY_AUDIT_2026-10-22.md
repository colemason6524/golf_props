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

Status: steps 2–5 pending (numbers, dead-path inventory, fixes, verdict).

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
| Incumbent parameters | `data/frozen_model_manifest.json` | manual freeze | `pipelines/weekly_forecast.py` | yes |
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
files claiming to be "the frozen manifest" is exactly the shape that rots. The
tracked one (`data/frozen_model_manifest.json`) is the one the code reads;
`docs/project_handoff.md:1065` points at the rolling-directory copy instead.
Documented, not changed: pinning which copy is canonical is a policy decision
(step 3 lists it as dead/legacy), and the params are provably equal.

#### 2.5.5 Split source of truth in git

`git ls-files data` = 16 files. Only the Bank of Utah grade artifacts and its
preserved leaderboard are tracked (force-added); `baycurrent_classic_2026`'s
grade and every `data/interim/weekly/*/grading.json` status sidecar exist only on
the VM (`data/interim/` is gitignored). A fresh clone therefore has one grade, a
single host has two, and the audit had to reconstruct the record from VM disk.
Recorded as a finding (step 4 adds no ignore rules — changing what is tracked is
a policy decision).
