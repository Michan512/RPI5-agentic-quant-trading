"""
Benchmark: cross-sectional momentum (Jegadeesh & Titman 1993; "12-1" form).

At each month end, rank stocks by their return from 12 months ago to 1 month
ago (skipping the latest month, which tends to reverse) and hold the top N
equally weighted until the next month end.
"""

import pandas as pd

from shared.strategy import PriceView, Strategy
from shared.universe import STOCKS


class Momentum(Strategy):
    name = "momentum_12_1"
    rebalance = "monthly"

    def __init__(self, top_n: int = 5, lookback: int = 252, skip: int = 21):
        self.top_n, self.lookback, self.skip = top_n, lookback, skip

    def params(self) -> dict:
        return {"top_n": self.top_n, "lookback_days": self.lookback, "skip_days": self.skip}

    def target_weights(self, data: PriceView) -> pd.Series:
        close = data.close[list(STOCKS)]
        if len(close) <= self.lookback:
            return pd.Series(dtype=float)
        past, recent = close.iloc[-1 - self.lookback], close.iloc[-1 - self.skip]
        score = (recent / past - 1).dropna()          # needs a full year of history
        top = score.nlargest(self.top_n).index
        return pd.Series(1.0 / self.top_n, index=top)
