# AGENTS.md — golf_props

Read `/Users/colemason/Predictions/docs/OPERATING_PLAN.md` first, then
this sport’s **VM** `.dashboard/checkpoint.json`. Those beat this file.
`docs/project_handoff.md` is the long scientific log. It is not the
current next-task if it disagrees with the checkpoint.

## Live product

PGA Tour forecast. The incumbent is the frozen **365-day / 8-round /
20-round-variance** simulator. A 2026-11-04 input refresh is activated
(canonical `pga_2001_2026_20261104`, manifest SHA `bb414ca1`, source
data through 2026-10-31, prospective holdout after 2026-11-05). Strength
parameters were not retuned. The open watch is the natural Austin
Championship board and its post-event grade (checkpoint target
2026-11-12).

This is a forecast-quality product (Brier / log loss versus a structural
baseline). Do not describe that gap as a betting edge. Sportsbook prices
stay outside the performance model.

## Live entrypoints

- Weekly forecast pipeline: `src/golf_props/pipelines/weekly_forecast.py`
- Discord: `src/golf_props/notifications/discord.py`
  (`GOLF_PROPS_DISCORD_WEBHOOK_URL`)
- Price addendum: `src/golf_props/notifications/price_addendum.py`
- Grades: `data/interim/reports/forecast_grading/<event>/report.md`
- Azure user timers: `sports-golf-forecast` (every two hours),
  `sports-golf-bovada`
- Tests: `PYTHONPATH=src python3 -m pytest` from this repo, using
  `.venv/bin/python`

## Do not touch / do not confuse

- This repo **has commits**. A Linux `.venv` is historically tracked.
  Never stage the rebuilt Mac `.venv`. Never `git add` the runtime.
- `data/` is generated research data and is intentionally large. Do not
  delete it because Git looks noisy.
- Do not call previously inspected events a prospective holdout.
- Do not apply an ordinary top-65 cut to no-cut events without a logged
  event-structure decision.
- The August 2026 TOUR Championship was a queued task in an older copy
  of this file. It is not the current next action.

## Research rules that still hold

- Preserve raw source data before normalization.
- Only information available before the prediction timestamp may enter
  a feature.
- Keep the frozen 365/8/20 simulator until a challenger beats it under
  the documented paired rolling protocol.
- Do not claim a betting edge from structural-baseline tests or the
  legacy exploratory Bovada value report.

## Where truth lives

- VM checkpoint / journal (current)
- `docs/project_handoff.md` (scientific log; checkpoint wins on “what next”)
- `docs/research_narrative.md`, `docs/azure_deployment.md`
