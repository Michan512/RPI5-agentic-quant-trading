"""
T10: low volatility across US sectors (the low-volatility benchmark idea, Baker,
Bradley & Wurgler 2011, applied to sector ETFs, which have no survivorship bias).

Monthly: hold the 3 sectors with the lowest volatility of daily returns over the
past year, 25% each (the sector cap), with the remaining 25% in short-term
Treasuries. No timing.
"""

import pandas as pd

from shared.strategy import PriceView, Strategy
from shared.universe import SECTOR_ETFS, etf


class SectorLowVol(Strategy):
    name = "sector_low_vol"
    rebalance = "monthly"

    def __init__(self, top_n: int = 3, lookback: int = 252):
        self.top_n, self.lookback = top_n, lookback

    def params(self) -> dict:
        return {"top_n": self.top_n, "vol_lookback_days": self.lookback, "weight_each": 0.25,
                "rest": "short_bond"}

    def target_weights(self, data: PriceView) -> pd.Series:
        close = data.close[list(SECTOR_ETFS)]
        if len(close) <= self.lookback:
            return pd.Series({etf("short_bond"): 1.0})
        rets = close.iloc[-1 - self.lookback:].pct_change(fill_method=None).iloc[1:]
        vol = rets.std()[rets.notna().all()]
        w = pd.Series(0.25, index=vol.nsmallest(self.top_n).index)
        w[etf("short_bond")] = 1.0 - w.sum()
        return w
