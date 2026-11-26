"""
The one strategy interface, used unchanged by backtests (PC) and live (Pi).

A strategy is: given price data up to and including the close of date T,
return target weights for the portfolio to hold from the open of T+1.

    class MyStrategy(Strategy):
        name = "my_strategy"
        rebalance = "monthly"            # "daily" | "weekly" | "monthly" | "once"
        def target_weights(self, data: PriceView) -> pd.Series: ...

Strategies never get the full panel. They get a PriceView, which can only
return rows on or before its as-of date, so looking ahead is impossible
through the interface. tests/ also runs a look-ahead test on every strategy.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd

from shared import limits
from shared.universe import TRADABLE, is_sector_etf, is_stock


class PriceView:
    """Read-only window onto a price panel, cut off at `asof` (inclusive)."""

    def __init__(self, panel: dict[str, pd.DataFrame], asof: pd.Timestamp):
        self._panel = panel
        self.asof = pd.Timestamp(asof)
        self._end = panel["close"].index.searchsorted(self.asof, side="right")

    def field(self, name: str) -> pd.DataFrame:
        """All rows of one field (open/high/low/close/volume) up to `asof`."""
        return self._panel[name].iloc[: self._end]

    @property
    def close(self) -> pd.DataFrame:
        return self.field("close")

    @property
    def open(self) -> pd.DataFrame:
        return self.field("open")

    @property
    def dates(self) -> pd.DatetimeIndex:
        return self._panel["close"].index[: self._end]

    def symbols(self) -> list[str]:
        return list(self._panel["close"].columns)


class Strategy(ABC):
    name: str = "unnamed"
    rebalance: str = "monthly"

    def params(self) -> dict:
        """Settings recorded in the trial log."""
        return {}

    @abstractmethod
    def target_weights(self, data: PriceView) -> pd.Series:
        """Weights by ticker (missing = 0). Must pass validate_weights()."""


class InvalidWeights(ValueError):
    pass


def validate_weights(weights: pd.Series) -> pd.Series:
    """Check a strategy's output against shared/limits.py. Returns a clean Series."""
    w = pd.Series(weights, dtype=float).fillna(0.0)
    w = w[w != 0.0]
    tol = limits.TOLERANCE
    if w.index.has_duplicates:
        raise InvalidWeights("duplicate tickers")
    unknown = set(w.index) - set(TRADABLE)
    if unknown:
        raise InvalidWeights(f"tickers outside the universe: {sorted(unknown)}")
    if limits.LONG_ONLY and (w < -tol).any():
        raise InvalidWeights(f"negative weights: {w[w < 0].to_dict()}")
    for t, x in w.items():
        if is_stock(t):
            cap = limits.MAX_WEIGHT_STOCK
        elif is_sector_etf(t):
            cap = limits.MAX_WEIGHT_SECTOR_ETF
        else:
            cap = limits.MAX_WEIGHT_ETF
        if x > cap + tol:
            raise InvalidWeights(f"{t} weight {x:.4f} exceeds cap {cap}")
    if w.sum() > limits.MAX_TOTAL_WEIGHT + tol:
        raise InvalidWeights(f"weights sum to {w.sum():.4f} > {limits.MAX_TOTAL_WEIGHT}")
    return w.clip(lower=0.0)


def is_rebalance_day(dates: pd.DatetimeIndex, i: int, freq: str) -> bool:
    """True if dates[i] is the last trading day of its period (signal at that close)."""
    if freq == "daily":
        return True
    if freq == "once":
        return i == 0
    if i == len(dates) - 1:
        return False  # period not finished yet: unknown whether it is the last day
    a, b = dates[i], dates[i + 1]
    if freq == "monthly":
        return (a.year, a.month) != (b.year, b.month)
    if freq == "weekly":
        return a.isocalendar()[:2] != b.isocalendar()[:2]
    raise ValueError(f"unknown rebalance frequency {freq!r}")
