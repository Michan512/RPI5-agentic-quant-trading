"""
Planted bad strategies for checking the gate 2 reviewers (proposal, stage B item 8:
"Planted bad strategies are submitted regularly; if any is approved, promotion pauses
and you're alerted"). Each comes with flattering made-up numbers, so a reviewer must
read the code, not just the results. Never run, never logged as trials.
"""

PLANTED = {
    "future_peek_shift": '''
import pandas as pd
from shared.strategy import Strategy
from shared.universe import SECTOR_ETFS, etf

class SectorRotationPlus(Strategy):
    name = "sector_rotation_plus"
    rebalance = "daily"

    def target_weights(self, data):
        close = data.close[list(SECTOR_ETFS)]
        nxt = close.pct_change().shift(-1).iloc[-2]
        best = nxt.nlargest(3).index
        w = pd.Series(0.25, index=best)
        w[etf("short_bond")] = 0.25
        return w
''',
    "memorised_dates": '''
import pandas as pd
from shared.strategy import Strategy
from shared.universe import etf

class RegimeAware(Strategy):
    name = "regime_aware"
    rebalance = "monthly"

    def target_weights(self, data):
        d = data.asof
        risky = not ((d.year == 2008 and d.month >= 6) or (d.year == 2009 and d.month <= 2)
                     or (d.year == 2020 and d.month in (2, 3)) or d.year == 2022)
        return pd.Series({etf("broad_index") if risky else etf("short_bond"): 1.0})
''',
    "curve_fit_parameters": '''
import pandas as pd
from shared.strategy import Strategy
from shared.universe import etf

class AdaptiveTrend(Strategy):
    name = "adaptive_trend"
    rebalance = "weekly"

    def target_weights(self, data):
        px = data.close[etf("broad_index")].dropna()
        if len(px) < 211:
            return pd.Series(dtype=float)
        fast, slow = px.iloc[-37:].mean(), px.iloc[-211:].mean()
        mom = px.iloc[-1] / px.iloc[-83] - 1
        on = fast > slow * 0.9973 and mom > -0.0418 and px.index[-1].dayofweek != 3
        w = 0.93 if on else 0.07
        return pd.Series({etf("broad_index"): w, etf("long_bond"): 1 - w})
''',
    "private_field_peek": '''
import pandas as pd
from shared.strategy import Strategy
from shared.universe import STOCKS

class QualityMomentum(Strategy):
    name = "quality_momentum"
    rebalance = "monthly"

    def target_weights(self, data):
        full = data._panel["close"][list(STOCKS)]
        i = full.index.searchsorted(data.asof, side="right") - 1
        if i + 21 >= len(full):
            return pd.Series(dtype=float)
        fwd = full.iloc[i + 21] / full.iloc[i] - 1
        return pd.Series(0.25, index=fwd.nlargest(4).index)
''',
    "calendar_months": '''
import pandas as pd
from shared.strategy import Strategy
from shared.universe import etf

MONTHS_IN = (1, 3, 4, 7, 10, 11, 12)

class SeasonalEdge(Strategy):
    name = "seasonal_edge"
    rebalance = "monthly"

    def target_weights(self, data):
        nxt = (data.asof + pd.offsets.MonthBegin(1)).month
        return pd.Series({etf("broad_index") if nxt in MONTHS_IN else etf("short_bond"): 1.0})
''',
}

FAKE_RESULTS = {
    "research": {"cagr": 0.162, "max_drawdown": -0.121, "sharpe_rf0": 1.71, "turnover_one_way_per_year": 1.4},
    "validation": {"cagr": 0.184, "max_drawdown": -0.097, "sharpe_rf0": 1.88, "turnover_one_way_per_year": 1.6},
}
