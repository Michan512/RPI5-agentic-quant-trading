# Stage D, ETF round 2

Research and validation only (holdout sealed). Costs included. Signals at the close, fills at the next open.

Caveat: Survivorship bias: the 19 single stocks are today's large-cap winners picked in 2026 (free data has no delisted stocks), so stock-picking results are biased upwards. The ETF part of the universe has traded continuously since 2006 and is not affected.

## Research (2007-01-01 to 2019-12-31)

| Strategy | CAGR | vs 60/40 | vs SPY | Worst fall | Sharpe | Turnover/yr |
|---|---:|---:|---:|---:|---:|---:|
| *buy_hold_index* | +8.7% | | | -55.2% | 0.53 | 4% |
| *sixty_forty* | +7.6% | | | -32.5% | 0.76 | 15% |
| inverse_vol_7 | +5.6% | -2.0% | -3.1% | -27.7% | 0.61 | 51% |
| trend_sixty_forty | +7.5% | -0.1% | -1.3% | -12.2% | 1.06 | 85% |
| vol_target_15 | +9.0% | +1.3% | +0.2% | -33.6% | 0.70 | 114% |
| sector_momentum_buffer | +8.2% | +0.6% | -0.6% | -16.8% | 0.81 | 184% |
| sector_low_vol | +8.3% | +0.6% | -0.5% | -28.4% | 0.82 | 62% |

## Validation (2020-01-01 to 2023-12-31)

| Strategy | CAGR | vs 60/40 | vs SPY | Worst fall | Sharpe | Turnover/yr |
|---|---:|---:|---:|---:|---:|---:|
| *buy_hold_index* | +12.1% | | | -33.7% | 0.62 | 13% |
| *sixty_forty* | +6.8% | | | -21.2% | 0.56 | 25% |
| inverse_vol_7 | +3.0% | -3.8% | -9.0% | -18.8% | 0.32 | 58% |
| trend_sixty_forty | +3.1% | -3.7% | -9.0% | -22.2% | 0.39 | 170% |
| vol_target_15 | +8.8% | +2.0% | -3.3% | -25.0% | 0.61 | 127% |
| sector_momentum_buffer | +5.3% | -1.5% | -6.8% | -20.1% | 0.49 | 328% |
| sector_low_vol | +8.7% | +1.9% | -3.3% | -22.0% | 0.66 | 55% |

## Decision (rule fixed before results)

- **inverse_vol_7** (trial 6): does not qualify: research: CAGR 5.6% not above 60/40 7.6%; validation: CAGR 3.0% not above 60/40 6.8%; validation: CAGR 3.0% not above the 5% bank rate
- **trend_sixty_forty** (trial 7): does not qualify: research: CAGR 7.5% not above 60/40 7.6%; validation: CAGR 3.1% not above 60/40 6.8%; validation: CAGR 3.1% not above the 5% bank rate
- **vol_target_15** (trial 8): EARNS a gate 1 attempt
- **sector_momentum_buffer** (trial 9): does not qualify: validation: CAGR 5.3% not above 60/40 6.8%; validation: turnover 328%/yr above the 300% limit
- **sector_low_vol** (trial 10): EARNS a gate 1 attempt

Total trials so far: 10
