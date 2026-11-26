"""
T3: sector momentum with a market trend filter (Moskowitz & Grinblatt 1999 on
sector momentum; 12-1 month lookback as in Jegadeesh & Titman; 200-day filter as
in Faber).

Monthly: if US stocks are above their 200-day average, hold the 3 strongest
sectors by 12-month return skipping the last month, 25% each (the sector cap),
with the remaining 25% in short-term Treasuries. Otherwise hold 7-10y Treasuries.
"""

import pandas as pd

from shared.strategy import PriceView, Strategy
from shared.universe import SECTOR_ETFS, etf


class SectorMomentum(Strategy):
    name = "sector_momentum_top3"
    rebalance = "monthly"

    def __init__(self, top_n: int = 3, lookback: int = 252, skip: int = 21, sma: int = 200):
        self.top_n, self.lookback, self.skip, self.sma = top_n, lookback, skip, sma

    def params(self) -> dict:
        return {"top_n": self.top_n, "lookback_days": self.lookback, "skip_days": self.skip,
                "trend_filter_sma_days": self.sma, "weight_each": 0.25}

    def target_weights(self, data: PriceView) -> pd.Series:
        spy = data.close[etf("broad_index")].dropna()
        close = data.close[list(SECTOR_ETFS)]
        if len(close) <= self.lookback or len(spy) < self.sma:
            return pd.Series({etf("mid_bond"): 1.0})
        if spy.iloc[-1] <= spy.iloc[-self.sma:].mean():
            return pd.Series({etf("mid_bond"): 1.0})
        score = (close.iloc[-1 - self.skip] / close.iloc[-1 - self.lookback] - 1).dropna()
        top = score.nlargest(self.top_n).index
        w = pd.Series(0.25, index=top)
        w[etf("short_bond")] = 1.0 - w.sum()
        return w
