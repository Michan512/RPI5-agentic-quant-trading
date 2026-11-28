"""
T8: volatility-managed US stocks (Moreira & Muir 2017, "Volatility-Managed
Portfolios"; long-only, no leverage).

Monthly: hold US stocks at weight min(1, target / realised volatility of the past
month), the rest in short-term Treasuries. Target = 15%/yr, about US stocks'
long-run volatility, so in calm markets it is fully invested and it cuts exposure
when markets get wild. Not tuned.
"""

import math

import pandas as pd

from shared.strategy import PriceView, Strategy
from shared.universe import etf


class VolTarget(Strategy):
    name = "vol_target_15"
    rebalance = "monthly"

    def __init__(self, target: float = 0.15, lookback: int = 21):
        self.target, self.lookback = target, lookback

    def params(self) -> dict:
        return {"target_vol_annual": self.target, "vol_lookback_days": self.lookback,
                "max_weight": 1.0, "off_asset": "short_bond"}

    def target_weights(self, data: PriceView) -> pd.Series:
        index = etf("broad_index")
        px = data.close[index].dropna()
        if len(px) <= self.lookback:
            return pd.Series({etf("short_bond"): 1.0})
        vol = px.iloc[-1 - self.lookback:].pct_change().iloc[1:].std() * math.sqrt(252)
        w = 1.0 if not vol > 0 else min(1.0, self.target / vol)
        out = {index: w}
        if w < 1.0:
            out[etf("short_bond")] = 1.0 - w
        return pd.Series(out)
