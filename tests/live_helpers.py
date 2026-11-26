"""Shared fixtures for the live-side tests: real (non-holdout) prices, fake broker, in-memory ledger."""

from __future__ import annotations

import pandas as pd

from live.broker.fake import FakeBroker
from live.engine.daily import DailyEngine
from live.engine.data import PanelProvider
from live.ledger.db import Ledger
from research.data.loader import load_panel
from research.strategies import BENCHMARKS
from shared.strategy import Strategy

_PANEL = None


def panel():
    global _PANEL
    if _PANEL is None:
        _PANEL = load_panel()
    return _PANEL


class ThreeWay(Strategy):
    """Fixed portfolio with several orders: 25% AAPL, 25% MSFT, 50% SPY."""
    name, rebalance = "three_way", "monthly"

    def target_weights(self, data):
        return pd.Series({"AAPL": 0.25, "MSFT": 0.25, "SPY": 0.5})


class TooBig(Strategy):
    name, rebalance = "too_big", "monthly"

    def target_weights(self, data):
        return pd.Series({"AAPL": 0.40})            # breaks the 25% per-stock cap


class Switcher(Strategy):
    """Index until end of March 2021, then short bonds."""
    name, rebalance = "switcher", "monthly"

    def target_weights(self, data):
        return pd.Series({"SPY": 1.0} if data.asof < pd.Timestamp("2021-03-31") else {"SHY": 1.0})


REGISTRY = {**BENCHMARKS, "three_way": ThreeWay, "too_big": TooBig, "switcher": Switcher}


def make(strategy="three_way", allocation=1.0, half_size=False, cash=5_000.0, **kw):
    broker, ledger = FakeBroker(cash), Ledger(":memory:")
    ledger.add_cash_flow("2020-01-01", cash, "initial deposit")
    engine = DailyEngine(broker, ledger, PanelProvider(panel()),
                         [{"strategy": strategy, "allocation": allocation, "half_size": half_size}],
                         registry=REGISTRY, kill_switch_path=kw.pop("kill_switch_path", None), **kw)
    return engine, broker, ledger


def session(broker, d):
    """Simulate the market on day d: fill queued orders at the open, mark at the close."""
    p = panel()
    d = pd.Timestamp(d)
    broker.open_session(p["open"].loc[d].dropna().to_dict(), session=str(d.date()))
    broker.mark(p["close"].loc[d].dropna().to_dict())


def replay(engine, broker, start, end):
    idx = panel()["close"].index
    days = idx[(idx >= pd.Timestamp(start)) & (idx <= pd.Timestamp(end))]
    equity, results = {}, {}
    for d in days:
        session(broker, d)
        results[d] = engine.run(d)
        equity[d] = broker.account().equity
    return pd.Series(equity), results
