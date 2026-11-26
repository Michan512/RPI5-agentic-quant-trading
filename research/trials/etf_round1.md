# Stage D, ETF round 1

Research and validation only (holdout sealed). Costs included. Signals at the close, fills at the next open.

Caveat: Survivorship bias: the 19 single stocks are today's large-cap winners picked in 2026 (free data has no delisted stocks), so stock-picking results are biased upwards. The ETF part of the universe has traded continuously since 2006 and is not affected.

## Research (2007-01-01 to 2019-12-31)

| Strategy | CAGR | vs 60/40 | vs SPY | Worst fall | Sharpe | Turnover/yr |
|---|---:|---:|---:|---:|---:|---:|
| *buy_hold_index* | +8.7% | | | -55.2% | 0.53 | 4% |
| *sixty_forty* | +7.6% | | | -32.5% | 0.76 | 15% |
| asset_trend_10m | +4.4% | -3.2% | -4.4% | -14.0% | 0.55 | 170% |
| dual_momentum_gem | +4.6% | -3.0% | -4.1% | -22.7% | 0.39 | 204% |
| sector_momentum_top3 | +7.8% | +0.2% | -0.9% | -16.5% | 0.76 | 281% |
| combo_t1_t2_t3 | +5.7% | -1.9% | -3.0% | -14.8% | 0.61 | 209% |

## Validation (2020-01-01 to 2023-12-31)

| Strategy | CAGR | vs 60/40 | vs SPY | Worst fall | Sharpe | Turnover/yr |
|---|---:|---:|---:|---:|---:|---:|
| *buy_hold_index* | +12.1% | | | -33.7% | 0.62 | 13% |
| *sixty_forty* | +6.8% | | | -21.2% | 0.56 | 25% |
| asset_trend_10m | +4.3% | -2.5% | -7.8% | -10.1% | 0.62 | 221% |
| dual_momentum_gem | +1.0% | -5.8% | -11.1% | -33.7% | 0.15 | 238% |
| sector_momentum_top3 | +6.2% | -0.6% | -5.8% | -20.9% | 0.55 | 389% |
| combo_t1_t2_t3 | +4.1% | -2.7% | -8.0% | -17.8% | 0.43 | 263% |

## Decision (rule fixed before results)

- **asset_trend_10m** (trial 2): does not qualify: research: CAGR 4.4% not above 60/40 7.6%; research: CAGR 4.4% not above the 5% bank rate; validation: CAGR 4.3% not above 60/40 6.8%; validation: CAGR 4.3% not above the 5% bank rate
- **dual_momentum_gem** (trial 3): does not qualify: research: CAGR 4.6% not above 60/40 7.6%; research: CAGR 4.6% not above the 5% bank rate; validation: CAGR 1.0% not above 60/40 6.8%; validation: CAGR 1.0% not above the 5% bank rate
- **sector_momentum_top3** (trial 4): does not qualify: validation: CAGR 6.2% not above 60/40 6.8%
- **combo_t1_t2_t3** (trial 5): does not qualify: research: CAGR 5.7% not above 60/40 7.6%; validation: CAGR 4.1% not above 60/40 6.8%; validation: CAGR 4.1% not above the 5% bank rate

Total trials so far: 5
