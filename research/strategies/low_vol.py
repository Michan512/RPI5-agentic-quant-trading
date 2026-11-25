"""
Benchmark: low volatility (Baker, Bradley & Wurgler 2011; Blitz & van Vliet 2007).

At each month end, hold the N stocks with the lowest volatility of daily
returns over the past year, equally weighted.
"""

import pandas as pd

from shared.strategy import PriceView, Strategy
from shared.universe import STOCKS


class LowVol(Strategy):
    name = "low_vol_252"
    rebalance = "monthly"

    def __init__(self, top_n: int = 5, lookback: int = 252):
        self.top_n, self.lookback = top_n, lookback

    def params(self) -> dict:
        return {"top_n": self.top_n, "lookback_days": self.lookback}

    def target_weights(self, data: PriceView) -> pd.Series:
        close = data.close[list(STOCKS)]
        if len(close) <= self.lookback:
            return pd.Series(dtype=float)
        rets = close.iloc[-1 - self.lookback:].pct_change(fill_method=None).iloc[1:]
        vol = rets.std()[rets.notna().all()]           # needs a full year of history
        low = vol.nsmallest(self.top_n).index
        return pd.Series(1.0 / self.top_n, index=low)
