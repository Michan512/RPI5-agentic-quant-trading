"""
Exit check from the proposal: the live engine's daily target weights must match
what the backtest code produces for the same days, and a replay through the
fake broker should track the backtest's equity.
"""

import unittest
from dataclasses import replace

import pandas as pd

from live.risk.limits import DEFAULT_LIMITS
from research.engine.backtest import run_backtest
from research.strategies import BENCHMARKS
from shared.strategy import PriceView, is_rebalance_day, validate_weights
from tests.live_helpers import make, panel, replay

START, END = "2021-01-04", "2021-12-31"
NO_STOPS = replace(DEFAULT_LIMITS, daily_loss_halt=1.0, drawdown_pause=1.0)


class Parity(unittest.TestCase):
    def test_targets_and_equity_match_backtest(self):
        for name, cls in BENCHMARKS.items():
            with self.subTest(strategy=name):
                # Compare the strategy pipeline only: switch off the turnover cap and loss stops
                # (tested separately in test_live_risk.py), which the backtest doesn't have.
                engine, broker, ledger = make(strategy=name, cap_turnover=False, limits=NO_STOPS)
                live_equity, results = replay(engine, broker, START, END)

                # 1. Target weights recorded by the live engine == strategy output from the backtest code.
                rebalance_days = [d for d, r in results.items() if r.message.startswith("rebalanced")]
                self.assertGreater(len(rebalance_days), 0)
                for d in rebalance_days:
                    expected = validate_weights(cls().target_weights(PriceView(panel(), d))).to_dict()
                    got = ledger.targets_on(str(d.date()))[name]
                    self.assertEqual(set(got), set(expected), f"{name} {d.date()}")
                    for t in expected:
                        self.assertAlmostEqual(got[t], expected[t], places=12)

                # 2. Same rebalance days as the backtest engine, and similar equity.
                bt = run_backtest(cls(), panel(), START, END)
                idx = panel()["close"].index
                window = idx[(idx >= pd.Timestamp(START)) & (idx <= pd.Timestamp(END))]
                freq = cls.rebalance
                expected_days = {window[0]} | {d for d in window[:-1]
                                               if is_rebalance_day(idx, idx.get_loc(d), freq)}
                live_days = {d for d in rebalance_days if d < window[-1]}   # backtest never signals on its last day
                self.assertEqual(live_days, expected_days, f"{name}: rebalance days differ")
                rel = (live_equity / S0(live_equity) - bt.equity / S0(bt.equity)).abs()
                self.assertLess(rel.max(), 0.015, f"{name}: live replay drifts from backtest by {rel.max():.2%}")


def S0(s):
    return s.iloc[0]


if __name__ == "__main__":
    unittest.main()
