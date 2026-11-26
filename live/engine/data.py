"""
Where the live engine gets prices. Live code never reads the research price
files (tests/test_holdout_lock.py enforces this).

  PanelProvider     wraps an in-memory panel (tests, replays)
  YFinanceProvider  downloads recent daily bars (laptop demo; the Pi may later
                    switch to a sturdier feed such as Alpaca market data)

check_fresh() refuses stale or incomplete data: no trade is better than a
trade on bad data.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Protocol

import pandas as pd

from shared.universe import ALL_SYMBOLS, TRADABLE

FIELDS = ("open", "high", "low", "close", "volume")


class DataProvider(Protocol):
    def panel(self, asof: pd.Timestamp) -> dict[str, pd.DataFrame]:
        """Wide frames (dates x symbols) for FIELDS, ending on or before `asof`."""


class StaleData(Exception):
    pass


def check_fresh(panel: dict[str, pd.DataFrame], run_date: pd.Timestamp) -> None:
    close = panel["close"]
    if close.empty or close.index[-1] != run_date:
        last = None if close.empty else close.index[-1].date()
        raise StaleData(f"latest bar is {last}, expected {run_date.date()}")
    missing = [s for s in TRADABLE if s not in close.columns or pd.isna(close[s].iloc[-1])]
    if missing:
        raise StaleData(f"no closing price on {run_date.date()} for: {missing}")


class PanelProvider:
    def __init__(self, panel: dict[str, pd.DataFrame]):
        self._panel = panel

    def panel(self, asof):
        end = self._panel["close"].index.searchsorted(pd.Timestamp(asof), side="right")
        return {f: df.iloc[:end] for f, df in self._panel.items()}


class YFinanceProvider:
    def __init__(self, years: int = 3, symbols=ALL_SYMBOLS):
        self.years, self.symbols = years, list(symbols)

    def panel(self, asof):
        import yfinance as yf

        asof = pd.Timestamp(asof)
        start = asof - timedelta(days=365 * self.years)
        raw = yf.download(self.symbols, start=start.strftime("%Y-%m-%d"),
                          end=(asof + timedelta(days=1)).strftime("%Y-%m-%d"),
                          progress=False, auto_adjust=True, group_by="column")
        out = {}
        for f in FIELDS:
            df = raw[f.capitalize()].copy()
            df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
            out[f] = df.reindex(columns=self.symbols)
        return out
