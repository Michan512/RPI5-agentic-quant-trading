"""
T1: asset-class trend following (Faber 2007, "A Quantitative Approach to Tactical
Asset Allocation"; the GTAA rule).

Equal weight across seven asset classes. At each month end, each one is held only
if its month-end price is above its 10-month average; otherwise that slice goes to
short-term Treasuries. Parameters are the paper's (10 months, monthly), not tuned.
"""

import pandas as pd

from shared.strategy import PriceView, Strategy
from shared.universe import etf, etfs

ASSETS = ("broad_index", "intl_developed", "emerging", "mid_bond", "gold", "real_estate", "commodities")


class AssetTrend(Strategy):
    name = "asset_trend_10m"
    rebalance = "monthly"

    def __init__(self, months: int = 10):
        self.months = months

    def params(self) -> dict:
        return {"assets": list(ASSETS), "sma_months": self.months, "off_asset": "short_bond"}

    def target_weights(self, data: PriceView) -> pd.Series:
        close = data.close[etfs(*ASSETS)]
        month_end = close.groupby(close.index.to_period("M")).last()
        slice_ = 1.0 / len(ASSETS)
        w: dict[str, float] = {}
        for t in close.columns:
            hist = month_end[t].dropna()
            on = len(hist) >= self.months and hist.iloc[-1] > hist.iloc[-self.months:].mean()
            key = t if on else etf("short_bond")
            w[key] = w.get(key, 0.0) + slice_
        return pd.Series(w)
