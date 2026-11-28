"""
Planted bad strategies for the Stage D exit checkpoint (proposal: "gate 1 correctly
rejects two planted strategies: one that peeks at future data and one deliberately
overfitted"). TEST CODE ONLY: never registered as a strategy, never logged as a trial.

Kept in their own module with no ticker literals, so the "rules only" check can't
be the reason they fail.
"""

import numpy as np
import pandas as pd

from shared.strategy import PriceView, Strategy
from shared.universe import STOCKS, etf

PEEK_DAYS = 21


def _best_next_month(full_close: pd.DataFrame, asof: pd.Timestamp) -> pd.Series:
    """Hold the 4 stocks that do best over the NEXT month: pure foresight."""
    stocks = full_close[list(STOCKS)]
    i = stocks.index.searchsorted(asof, side="right") - 1
    if i + PEEK_DAYS >= len(stocks):
        return pd.Series(dtype=float)
    fwd = (stocks.iloc[i + PEEK_DAYS] / stocks.iloc[i] - 1).dropna()
    return pd.Series(0.25, index=fwd.nlargest(4).index)


class PeekerBackDoor(Strategy):
    """Peeks by reaching past the PriceView's cut through its private panel."""
    name, rebalance = "planted_peeker_backdoor", "monthly"

    def target_weights(self, data: PriceView) -> pd.Series:
        return _best_next_month(data._panel["close"], data.asof)


class PeekerPrivateCopy(Strategy):
    """Peeks through its own copy of the full history (as if it read the data files itself)."""
    name, rebalance = "planted_peeker_private_copy", "monthly"
    full_close: pd.DataFrame | None = None          # set by the test before running

    def target_weights(self, data: PriceView) -> pd.Series:
        return _best_next_month(self.full_close, data.asof)
