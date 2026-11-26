"""Benchmark: 60% US stocks / 40% 7-10y Treasuries, rebalanced monthly. The classic multi-asset yardstick."""

import pandas as pd

from shared.strategy import PriceView, Strategy
from shared.universe import etf


class SixtyForty(Strategy):
    name = "sixty_forty"
    rebalance = "monthly"

    def params(self) -> dict:
        return {"broad_index": 0.6, "mid_bond": 0.4}

    def target_weights(self, data: PriceView) -> pd.Series:
        return pd.Series({etf("broad_index"): 0.6, etf("mid_bond"): 0.4})
