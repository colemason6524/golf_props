# Bank of Utah Championship Prospective Forecast Grade

## Scope

- Classification: genuinely prospective frozen forecast.
- Graded targets: top-20, top-10, top-5, winner.
- `make_cut` excluded from graded targets.
- Results source: CBS Sports (https://www.cbssports.com/golf/leaderboard/pga-tour/31000135/bank-of-utah-championship/).
- Actual winner: Austin Smotherman.
- Highest forecast winner probability: Maverick McNealy.
- Placement rows excluded under the established withdrawal rule: Austin Eckroat, C.T. Pan, Rasmus Neergaard-Petersen, Vince Whaley.
- Forecast players without a results row (pre-start withdrawals, excluded): K.H. Lee, Lanto Griffin, Taylor Pendrith.
- Results rows without a matching forecast (late entrants, ignored): 11.
- Cross-source name aliases applied: 10.

## Metrics

| Target | Graded | Actual | Expected | Brier | Structural | Improvement | Rolling Brier | Log loss | Rolling log loss |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| top20 | 108 | 19 | 20.988 | 0.1445 | 0.1451 | +0.0006 | 0.1307 | 0.4614 | 0.4192 |
| top10 | 108 | 11 | 10.884 | 0.0925 | 0.0916 | -0.0010 | 0.0777 | 0.3336 | 0.2777 |
| top5 | 108 | 5 | 5.601 | 0.0448 | 0.0442 | -0.0006 | 0.0434 | 0.1909 | 0.1736 |
| winner | 108 | 1 | 0.941 | 0.0092 | 0.0092 | -0.0001 | 0.0078 | 0.0546 | 0.0415 |

## Interpretation

The sign of `Improvement` is structural-baseline Brier minus model Brier, so positive is better. `Rolling Brier` and `Rolling log loss` are historical aggregate expectations, not thresholds that one event must beat.

This single 108-player graded event is too small to estimate a stable calibration curve or justify retuning. The frozen 365/8/20 incumbent remains unchanged; accumulate additional genuinely prospective events before drawing model-level conclusions.
