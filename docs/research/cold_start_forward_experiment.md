# Cold-start uncertainty challenger — registered paired forward experiment

Status: **prospective / disabled / no activation**. Registered 2026-11-03 before
any challenger result was inspected. Incumbent remains the frozen 365-day /
8-round-mean / 20-round-variance simulator.

## Hypothesis

The incumbent shrinks a player's mean toward the tour mean but simulates each
round with the player's performance variance. A player with very few effective
rounds therefore gets a confidently-estimated mean. The 2026-10-28 research
check-in proposed inflating cold-start uncertainty. This experiment tests that
one fixed form; it is not a threshold search and does not add a new data source.

## Fixed candidate `cold_start_variance_v1`

- `e` = archived `effective_rounds`; `p` = frozen `prior_rounds` (8.0).
- reliability `r = e / (e + p)`.
- variance multiplier `f = 2 - r`; `std' = std * sqrt(f)`.
- Everything else (means, seed, simulation count, cut rule/size, field) is taken
  unchanged from the event's immutable archive.

## Paired protocol (per future prospective event)

1. Wait for the normal pre-start frozen archive.
2. Offline, run:
   `golf-props cold-start-challenger --archive-dir <archive> --output-dir <new dir>`.
3. Keep the incumbent `predictions.csv` and the challenger `predictions.csv`
   unmodified.
4. After the normal event grade, compare both on the same graded cohort using
   `golf-props review-prospective-golf --cold-start-challenger`.
5. Accumulate at least 8 paired prospective events. Single events are never
   actionable.

## Pre-registered decision rule

- Change is considered only with ≥8 paired events, positive equal-event top-20
  Brier improvement, at least 6/8 positive events, an event-bootstrap 90% CI
  lower bound above zero, and no target degrading by more than 0.001.
- Any such outcome still requires an exact reviewed release and a separate
  activation decision; this experiment cannot activate itself.
- Prices stay outside the performance comparison. No sportsbook price is an
  input to the challenger.

## Boundaries

- Never write inside an archive; the CLI refuses that.
- The challenger manifest records `status: disabled` and
  `production_effect: none`.
- No public send, no production forecast path reads this module, and no
  historical grade is rewritten.
