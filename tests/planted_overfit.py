"""
Planted overfitted strategy (Stage D exit checkpoint). TEST CODE ONLY: never
registered as a strategy, never logged as a trial. It is honest about data (uses
only the PriceView); its flaw is that it was picked as the best of many tries.
"""

import numpy as np
import pandas as pd

from shared.strategy import PriceView, Strategy
from shared.universe import etf


def month_mask_returns(close: pd.DataFrame, masks: np.ndarray) -> np.ndarray:
    """Daily returns of 'index in the months set in the mask, short bonds otherwise'.
    masks: (n_masks, 12) of 0/1. Returns (n_masks, n_days)."""
    idx, bond = etf("broad_index"), etf("short_bond")
    r_idx = close[idx].pct_change().fillna(0).to_numpy()
    r_bond = close[bond].pct_change().fillna(0).to_numpy()
    month = close.index.month.to_numpy() - 1
    m = masks[:, month].astype(bool)
    return np.where(m, r_idx, r_bond)


def fit_calendar_mask(close: pd.DataFrame, n_trials: int = 200, seed: int = 0):
    """Deliberate overfitting: try n_trials random 'which months to be invested' masks
    on the visible history and keep the best by Sharpe. Returns (best_mask, daily Sharpes)."""
    rng = np.random.default_rng(seed)
    masks = rng.integers(0, 2, size=(n_trials, 12))
    rets = month_mask_returns(close, masks)
    sd = rets.std(axis=1, ddof=1)
    sharpes = np.where(sd > 0, rets.mean(axis=1) / np.where(sd > 0, sd, 1), 0.0)
    return masks[int(np.argmax(sharpes))], sharpes.tolist()


class OverfitCalendar(Strategy):
    """Holds the index only in the calendar months that happened to do best in the past."""
    name, rebalance = "planted_overfit_calendar", "monthly"
    months_in: tuple = ()                            # set by the test from fit_calendar_mask

    def params(self) -> dict:
        return {"months_in": list(self.months_in)}

    def target_weights(self, data: PriceView) -> pd.Series:
        # Signal at the month-end close; the fill is next month's open, so pick by NEXT month.
        nxt = (data.asof + pd.offsets.MonthBegin(1)).month
        asset = etf("broad_index") if nxt in self.months_in else etf("short_bond")
        return pd.Series({asset: 1.0})
