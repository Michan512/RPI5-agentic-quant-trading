"""T4: one third each of T1 (asset trend), T2 (dual momentum) and T3 (sector momentum)."""

import pandas as pd

from research.strategies.asset_trend import AssetTrend
from research.strategies.dual_momentum import DualMomentum
from research.strategies.sector_momentum import SectorMomentum
from shared.strategy import PriceView, Strategy


class Combo(Strategy):
    name = "combo_t1_t2_t3"
    rebalance = "monthly"

    def __init__(self):
        self.parts = [AssetTrend(), DualMomentum(), SectorMomentum()]

    def params(self) -> dict:
        return {"parts": {p.name: p.params() for p in self.parts}, "weights": "1/3 each"}

    def target_weights(self, data: PriceView) -> pd.Series:
        total = pd.Series(dtype=float)
        for p in self.parts:
            total = total.add(p.target_weights(data) / len(self.parts), fill_value=0.0)
        return total
