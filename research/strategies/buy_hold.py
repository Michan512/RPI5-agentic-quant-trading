"""Benchmark: buy the broad index ETF once and hold it."""

import pandas as pd

from shared.strategy import PriceView, Strategy
from shared.universe import etf


class BuyHold(Strategy):
    name = "buy_hold_index"
    rebalance = "once"

    def params(self) -> dict:
        return {"asset": "broad_index"}

    def target_weights(self, data: PriceView) -> pd.Series:
        return pd.Series({etf("broad_index"): 1.0})
