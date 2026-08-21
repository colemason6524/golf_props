# Continuation Prompt

Copy everything inside the block below into a new LLM coding session.

```text
You are taking over development of this repository:

/Users/colemason/Documents/golf_props

Act directly with your terminal and file-editing tools. Before making changes:

1. Run `git status --short --branch`.
2. Read `AGENTS.md` completely.
3. Read `docs/project_handoff.md` completely. Treat it as the authoritative
   current state, decision log, scientific guardrail, and next-task document.
4. Read `docs/research_narrative.md` completely. It tells the story of what was
   learned, what succeeded, what failed, the current theory, and the outward
   risks the previous session wants you to question.
5. Read `README.md` and any linked document relevant to the task.
6. Run `PYTHONPATH=src python3 -m pytest`.

What this project is:

- A PGA golf props research prototype inspired by Bill Benter-style discipline.
- Goal: point-in-time-safe player outcome probabilities, then later compare them
  with archived sportsbook prices to test whether the market is miscalibrated.
- Not a betting bot. No bankroll automation. No edge claims from structural
  baselines or the legacy Bovada value report.

Progress framing (do not get this wrong):

- Do NOT say the project is literally “halfway through.” Phases are unequal.
- We are advanced on the performance-model foundation.
- We are still early on prospective validation and market-edge research.
- The binding gap is prospective evidence, not more model complexity and not
  sportsbook access.

Important repository state:

- There are currently no Git commits; most project files are untracked.
- Large data and generated reports under `data/` are intentionally ignored but
  are important local research state.
- Do not delete, clean, reset, or revert anything unless explicitly asked.
- The verified test suite had 117 passing tests at the 2026-08-20 handoff.

Important model state:

- Frozen incumbent: 365-day half-life, 8-round mean prior, 20-round variance
  prior, seeded joint-field simulator. Ordinary top-65-and-ties cut is the
  historical default; an explicit `no_cut` event-structure rule now exists and
  is used for no-cut playoff events without changing 365/8/20 strength.
- Supported by four rolling evaluation folds covering 182 tournaments versus a
  structural field baseline. This is NOT proof of betting edge.
- Calibration slopes > 1 suggest compressed probabilities; watch this in
  prospective grading.
- Reviewed course crosswalk restored latest-window matched-course player
  coverage from 0% to 62.9886%.
- Same-course residual challenger was implemented/evaluated after identity
  repair and was NOT promoted (tiny unstable gains; 2025 fold chose zero).
- Phase 6 is therefore only partially started: residual challenger rejected;
  richer course-fit / strokes-gained enrichment has not started.
- Legacy Bovada value report uses older heuristic rankings, not the frozen
  simulator, and must remain labeled exploratory.
- Bovada is the working automated no-browser odds source. DraftKings sportsbook
  remains Akamai-blocked, DraftKings Predictions is stale/unreliable, and
  FanDuel has no stable collector.

Completed and settled:

- Course identity crosswalk: `config/course_aliases.csv`
  (`Pete Dye Stadium Course PGA West` deliberately unresolved).
- Manifest-driven `predict-current-event` workflow: hash verification, locked
  365/8/20, prospective eligibility, forecast bundle outputs, explicit
  `--cut-rule no_cut` support, and a pre-start timestamp guard
  (`--event-start-at-utc`).
- Wyndham Championship 2026 dry-run at
  `data/interim/reports/wyndham_championship_2026_frozen_simulation/`
  is permanently labeled `retrospective_replay` because start date equals
  `prospective_holdout_after=2026-08-06`. Do NOT treat it as prospective
  evidence.

Exact next task:

1. The event-structure question is now resolved in code: `predict-current-event`
   accepts `--cut-rule {top_n_and_ties,no_cut}` and requires a timezone-aware
   `--event-start-at-utc` strictly after run creation for prospective runs.
   Do NOT change frozen strength parameters (365/8/20).
2. FedEx St. Jude (2026-08-13) and BMW (2026-08-20) are no longer prospectively
   eligible. The next genuinely eligible event is the 2026 TOUR Championship:
   competitive rounds 2026-08-27 to 2026-08-30 at East Lake, 30 players, no
   cut, 72-hole stroke play, all players at even par.
3. Its official top-30 field is final only after BMW concludes (2026-08-23).
   After that, preserve the authoritative official field, resolve identities
   safely, verify the first-tee UTC timestamp once tee times are posted, and run
   `predict-current-event --cut-rule no_cut --event-start-at-utc <verified>`
   WITHOUT `--allow-retrospective`, strictly before the Thursday 2026-08-27
   first tee.
4. Archive the bundle unchanged; grade top-20/top-10/top-5/winner later without
   retuning. `make_cut` is structural (1.0) under no-cut and is not a
   substantive target. Repeat across future events.
5. Forbidden: inventing a cut that does not exist, backfilling after tee time,
   counting Wyndham as OOS, or using odds inside the performance model.
6. Bovada timestamp collection may continue in parallel but must not block
   prospective performance validation.

Watch-outs the previous session wants questioned:

- Playoff no-cut / special formats vs top-65 simulator assumption.
- Missing the TOUR Championship window after Thursday 2026-08-27 tee times.
- Using Bovada as field-of-record instead of official PGA field.
- Stale local history (`source_data_through=2026-07-11`) vs market knowledge.
- Calibration compression and weak structural benchmarks tempting overclaim.
- Silent name-match fallbacks degrading forecasts.
- No Git commits / ignored `data/` durability risk.

Do not reopen casually:

- Incumbent remains 365/8/20 until a challenger wins the paired protocol.
- Course residual challenger remains not promoted.
- Wyndham remains retrospective only.
- Legacy Bovada value report remains exploratory only.
- No-cut support and the pre-start guard are structural; they do not retune
  strength and do not imply support for starting strokes or other special
  formats.

Keep `docs/project_handoff.md`, `docs/research_narrative.md`, README, roadmap,
schema documentation, and this continuation prompt current as you work. At the
end, report exact files changed, commands run, test results, generated
artifacts, empirical findings, and the new stopping point.
```
