# Butterfield Bermuda Championship Prospective Forecast Grade

## Scope

- Classification: genuinely prospective frozen forecast.
- Graded targets: top-20, top-10, top-5, winner.
- `make_cut` excluded from graded targets.
- Results source: CBS Sports (https://www.cbssports.com/golf/leaderboard/pga-tour/31000146/butterfield-bermuda-championship/).
- Actual winner: Austin Smotherman.
- Highest forecast winner probability: Eric Cole.
- Placement rows excluded under the established withdrawal rule: Max Greyserman.
- Forecast players without a results row (pre-start withdrawals, excluded): Lanto Griffin, Rasmus Højgaard.
- Results rows without a matching forecast (late entrants, ignored): 2.
- Cross-source name aliases applied: 11.

## Metrics

| Target | Graded | Actual | Expected | Brier | Structural | Improvement | Rolling Brier | Log loss | Rolling log loss |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| top20 | 117 | 23 | 21.718 | 0.1549 | 0.1586 | +0.0037 | 0.1307 | 0.4830 | 0.4192 |
| top10 | 117 | 10 | 11.258 | 0.0762 | 0.0782 | +0.0020 | 0.0777 | 0.2793 | 0.2777 |
| top5 | 117 | 5 | 5.770 | 0.0396 | 0.0409 | +0.0013 | 0.0434 | 0.1614 | 0.1736 |
| winner | 117 | 1 | 0.958 | 0.0085 | 0.0085 | -0.0000 | 0.0078 | 0.0484 | 0.0415 |

## Interpretation

The sign of `Improvement` is structural-baseline Brier minus model Brier, so positive is better. `Rolling Brier` and `Rolling log loss` are historical aggregate expectations, not thresholds that one event must beat.

This single 117-player graded event is too small to estimate a stable calibration curve or justify retuning. The frozen 365/8/20 incumbent remains unchanged; accumulate additional genuinely prospective events before drawing model-level conclusions.
