"""
Benchmark: trend following on the broad index (Faber 2007 style, 200-day average).

At each month end: if the index ETF closed above its 200-day simple moving
average, hold it; otherwise hold a short-term Treasury ETF (or cash).
"""

import pandas as pd

from shared.strategy import PriceView, Strategy
from shared.universe import etf


class Trend(Strategy):
    name = "trend_sma200"
    rebalance = "monthly"

    def __init__(self, window: int = 200, off_asset: str | None = "short_bond"):
        self.window, self.off_asset = window, off_asset

    def params(self) -> dict:
        return {"sma_days": self.window, "off_asset": self.off_asset or "cash"}

    def target_weights(self, data: PriceView) -> pd.Series:
        index = etf("broad_index")
        px = data.close[index].dropna()
        if len(px) < self.window:
            return pd.Series(dtype=float)
        if px.iloc[-1] > px.iloc[-self.window:].mean():
            return pd.Series({index: 1.0})
        if self.off_asset:
            return pd.Series({etf(self.off_asset): 1.0})
        return pd.Series(dtype=float)
