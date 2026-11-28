"""
T6: inverse-volatility weighting across asset classes (a simple risk-parity form;
Maillard, Roncalli & Teiletche 2010 for the full version).

Monthly: weight each of the seven asset-class ETFs by 1 / (its volatility of daily
returns over the past 3 months), scaled to sum to 1. Always fully invested, no
timing. Same seven assets as T1 so the two are comparable.
"""

import pandas as pd

from shared.strategy import PriceView, Strategy
from shared.universe import etf, etfs

ASSETS = ("broad_index", "intl_developed", "emerging", "mid_bond", "gold", "real_estate", "commodities")


class InverseVol(Strategy):
    name = "inverse_vol_7"
    rebalance = "monthly"

    def __init__(self, lookback: int = 63):
        self.lookback = lookback

    def params(self) -> dict:
        return {"assets": list(ASSETS), "vol_lookback_days": self.lookback}

    def target_weights(self, data: PriceView) -> pd.Series:
        close = data.close[etfs(*ASSETS)]
        if len(close) <= self.lookback:
            return pd.Series({etf("short_bond"): 1.0})
        rets = close.iloc[-1 - self.lookback:].pct_change(fill_method=None).iloc[1:]
        vol = rets.std()[rets.notna().all()]
        vol = vol[vol > 0]
        if vol.empty:
            return pd.Series({etf("short_bond"): 1.0})
        inv = 1.0 / vol
        return inv / inv.sum()
