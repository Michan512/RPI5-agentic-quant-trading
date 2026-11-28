"""
T7: trend-filtered 60/40 (combines two benchmark signals: the 60/40 mix and the
200-day trend rule of Faber 2007).

Monthly: 40% in 7-10y Treasuries always. The 60% stock slice is in US stocks while
they close above their 200-day average, otherwise in short-term Treasuries. At
most 60% of the portfolio ever switches, unlike the 100% flips of the plain trend rule.
"""

import pandas as pd

from shared.strategy import PriceView, Strategy
from shared.universe import etf


class TrendSixtyForty(Strategy):
    name = "trend_sixty_forty"
    rebalance = "monthly"

    def __init__(self, sma: int = 200):
        self.sma = sma

    def params(self) -> dict:
        return {"stocks": 0.6, "mid_bond": 0.4, "trend_filter_sma_days": self.sma, "off_asset": "short_bond"}

    def target_weights(self, data: PriceView) -> pd.Series:
        index = etf("broad_index")
        px = data.close[index].dropna()
        on = len(px) >= self.sma and px.iloc[-1] > px.iloc[-self.sma:].mean()
        return pd.Series({index if on else etf("short_bond"): 0.6, etf("mid_bond"): 0.4})
