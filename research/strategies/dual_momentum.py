"""
T2: dual momentum (Antonacci 2014, "Dual Momentum Investing"; the GEM rule).

Monthly: compare the 12-month return of US stocks and international stocks and
pick the stronger (relative momentum). Hold it only if it also beat short-term
Treasuries (absolute momentum); otherwise hold 7-10y Treasuries. (The book uses
an aggregate bond fund; IEF is the closest fund in this universe.)
"""

import pandas as pd

from shared.strategy import PriceView, Strategy
from shared.universe import etf


class DualMomentum(Strategy):
    name = "dual_momentum_gem"
    rebalance = "monthly"

    def __init__(self, lookback: int = 252):
        self.lookback = lookback

    def params(self) -> dict:
        return {"lookback_days": self.lookback, "risky": ["broad_index", "intl_developed"],
                "cash_proxy": "short_bond", "defensive": "mid_bond"}

    def target_weights(self, data: PriceView) -> pd.Series:
        us, intl, cash = etf("broad_index"), etf("intl_developed"), etf("short_bond")
        close = data.close[[us, intl, cash]]
        if len(close) <= self.lookback:
            return pd.Series({etf("mid_bond"): 1.0})
        ret = close.iloc[-1] / close.iloc[-1 - self.lookback] - 1
        best = us if ret[us] >= ret[intl] else intl
        return pd.Series({best: 1.0} if ret[best] > ret[cash] else {etf("mid_bond"): 1.0})
