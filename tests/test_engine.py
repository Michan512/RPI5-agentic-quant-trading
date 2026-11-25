import unittest

import pandas as pd

from research.engine import settings as S
from research.engine.backtest import run_backtest
from shared.strategy import Strategy
from tests.helpers import synthetic_panel


class AllIn(Strategy):
    name, rebalance = "all_in_spy", "once"

    def target_weights(self, data):
        return pd.Series({"SPY": 1.0})


class Seen(Strategy):
    """Records what it was shown."""
    name, rebalance = "seen", "daily"

    def __init__(self):
        self.seen = []

    def target_weights(self, data):
        self.seen.append((data.asof, data.close.index[-1]))
        return pd.Series({"AAPL": 0.25})


class Engine(unittest.TestCase):
    def test_fills_at_next_open(self):
        p = synthetic_panel()
        d0, d1 = p["close"].index[:2]
        r = run_backtest(AllIn(), p, d0, p["close"].index[-1])
        t = r.trades.iloc[0]
        self.assertEqual(t["date"], d1)              # signal at d0's close, fill at d1's open
        self.assertAlmostEqual(t["price"], p["open"].loc[d1, "SPY"])

    def test_costs_on_flat_prices(self):
        p = synthetic_panel(flat=True)
        r = run_backtest(AllIn(), p, p["close"].index[0], p["close"].index[-1])
        rate = (S.FEE_BPS + S.SLIPPAGE_BPS) / 1e4
        # One buy of (almost) all cash; the only loss is that buy's cost.
        self.assertAlmostEqual(r.equity.iloc[-1], S.INITIAL_CASH * (1 - rate / (1 + rate)), places=6)
        self.assertGreater(r.costs, 0)

    def test_never_more_than_fully_invested(self):
        p = synthetic_panel()
        r = run_backtest(AllIn(), p, p["close"].index[0], p["close"].index[-1])
        self.assertTrue((r.weights.sum(axis=1) <= 1 + 1e-9).all())

    def test_strategy_never_sees_future(self):
        p = synthetic_panel()
        s = Seen()
        run_backtest(s, p, p["close"].index[10], p["close"].index[50])
        for asof, last_row in s.seen:
            self.assertEqual(asof, last_row)


if __name__ == "__main__":
    unittest.main()
