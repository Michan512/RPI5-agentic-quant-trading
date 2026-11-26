"""
Benchmark: hold every stock in the universe in equal amounts, rebalanced monthly.

This is the fair yardstick for any stock-picking idea. The universe is biased
(today's winners), so beating SPY proves little; a stock picker has to beat
simply owning all of the same stocks.
"""

import pandas as pd

from shared import limits
from shared.strategy import PriceView, Strategy
from shared.universe import STOCKS


class EqualWeight(Strategy):
    name = "equal_weight_universe"
    rebalance = "monthly"

    def params(self) -> dict:
        return {"universe": "all stocks", "weighting": "equal, capped at the per-stock limit"}

    def target_weights(self, data: PriceView) -> pd.Series:
        last = data.close[list(STOCKS)].iloc[-1]
        trading = last[last.notna()].index
        if len(trading) == 0:
            return pd.Series(dtype=float)
        return pd.Series(min(1.0 / len(trading), limits.MAX_WEIGHT_STOCK), index=trading)
