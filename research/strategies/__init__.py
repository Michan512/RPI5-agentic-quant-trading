"""One file per strategy, each implementing the shared strategy interface."""

from research.strategies.buy_hold import BuyHold
from research.strategies.equal_weight import EqualWeight
from research.strategies.low_vol import LowVol
from research.strategies.momentum import Momentum
from research.strategies.sixty_forty import SixtyForty
from research.strategies.trend import Trend

BENCHMARKS = {
    "buy_hold_index": BuyHold,
    "momentum_12_1": Momentum,
    "trend_sma200": Trend,
    "low_vol_252": LowVol,
    "equal_weight_universe": EqualWeight,
    "sixty_forty": SixtyForty,
}

# Stage D candidates (each evaluation is a logged trial; not benchmarks).
from research.strategies.asset_trend import AssetTrend  # noqa: E402
from research.strategies.combo import Combo  # noqa: E402
from research.strategies.dual_momentum import DualMomentum  # noqa: E402
from research.strategies.sector_momentum import SectorMomentum  # noqa: E402

ETF_ROUND1 = {c.name: c for c in (AssetTrend, DualMomentum, SectorMomentum, Combo)}
