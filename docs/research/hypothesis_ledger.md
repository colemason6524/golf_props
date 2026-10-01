# Golf Research Hypothesis Ledger

This ledger keeps fast research separate from the frozen forecast board. A
challenger may be developed quickly, but it cannot alter the production forecast
without a predeclared, point-in-time-safe, tournament-clustered evaluation.

## Rules

1. Declare the hypothesis, data cutoff, baseline, challenger, and metric before
   evaluating outcomes.
2. Keep the frozen 365-day / 8-round / 20-round-variance model as incumbent.
3. Evaluate by tournament, not independent player rows, for uncertainty.
4. Do not use sportsbook prices as performance-model features.
5. A prospective event is never reused as a new holdout after inspection.
6. Promotion requires stable out-of-sample improvement against the incumbent and
   a relevant market-aware diagnostic where prices are available.

## Initial Queue

| ID | Hypothesis | Status | Next evidence |
|---|---|---|---|
| G1 | Fresh post-July results improve current strength | proposed | Build append-only candidate; compare on future events only |
| G2 | Multi-book prices and power de-vig provide a useful reference layer | proposed | Preserve event-keyed snapshots and closing prices |
| G3 | Matchups/top-10/top-20 are less sparse than outrights | proposed | Add outcome adapters and grade separate market cohorts |
| G4 | Course architecture and shot profile add stable signal | proposed | Acquire point-in-time-safe public features; paired challenger |
| G5 | Weather and tee-wave information improves pre-start probabilities | proposed | Archive forecasts, not observed conditions, before tee time |
| G6 | Withdrawal/start-status risk improves placement calibration | proposed | Define status source and graded withdrawal policy |

No item is promoted by this document alone.
