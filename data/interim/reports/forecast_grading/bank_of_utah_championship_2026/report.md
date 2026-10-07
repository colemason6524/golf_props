# Bank of Utah Championship Prospective Forecast Grade

## Scope

- Classification: genuinely prospective frozen forecast.
- Graded targets: top-20, top-10, top-5, winner.
- `make_cut` excluded from graded targets.
- Results source: CBS Sports (https://www.cbssports.com/golf/leaderboard/pga-tour/31000135/bank-of-utah-championship/).
- Actual winner: Austin Smotherman.
- Highest forecast winner probability: Maverick McNealy.
- Placement rows excluded under the established withdrawal rule: Austin Eckroat, C.T. Pan, Rasmus Neergaard-Petersen, Vince Whaley.
- Forecast players without a results row (pre-start withdrawals, excluded): K.H. Lee, Lanto Griffin, Rasmus Højgaard, Taylor Pendrith.
- Results rows without a matching forecast (late entrants, ignored): 12.
- Cross-source name aliases applied: 9.

## Metrics

| Target | Graded | Actual | Expected | Brier | Structural | Improvement | Rolling Brier | Log loss | Rolling log loss |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| top20 | 107 | 19 | 20.742 | 0.1453 | 0.1461 | +0.0009 | 0.1307 | 0.4631 | 0.4192 |
| top10 | 107 | 11 | 10.746 | 0.0932 | 0.0923 | -0.0009 | 0.0777 | 0.3353 | 0.2777 |
| top5 | 107 | 5 | 5.524 | 0.0452 | 0.0445 | -0.0006 | 0.0434 | 0.1919 | 0.1736 |
| winner | 107 | 1 | 0.926 | 0.0093 | 0.0093 | -0.0001 | 0.0078 | 0.0549 | 0.0415 |

## Interpretation

The sign of `Improvement` is structural-baseline Brier minus model Brier, so positive is better. `Rolling Brier` and `Rolling log loss` are historical aggregate expectations, not thresholds that one event must beat.

This single 107-player graded event is too small to estimate a stable calibration curve or justify retuning. The frozen 365/8/20 incumbent remains unchanged; accumulate additional genuinely prospective events before drawing model-level conclusions.
