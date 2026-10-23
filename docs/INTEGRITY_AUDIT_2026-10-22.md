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
