"""One file per strategy, each implementing the shared strategy interface."""

from research.strategies.buy_hold import BuyHold
from research.strategies.equal_weight import EqualWeight
from research.strategies.low_vol import LowVol
from research.strategies.momentum import Momentum
from research.strategies.trend import Trend

BENCHMARKS = {
    "buy_hold_index": BuyHold,
    "momentum_12_1": Momentum,
    "trend_sma200": Trend,
    "low_vol_252": LowVol,
    "equal_weight_universe": EqualWeight,
}
