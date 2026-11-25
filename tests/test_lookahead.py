"""Look-ahead test on every strategy: changing prices after T must not change the weights for T."""

import unittest

import pandas as pd

from research.data.loader import load_panel
from research.engine.lookahead import check_no_lookahead
from research.strategies import BENCHMARKS
from research.strategies.xgb_candidate import XGBCandidate
from shared.strategy import Strategy

DATES = ["2012-06-29", "2016-03-31", "2021-09-30"]


class Cheat(Strategy):
    name, rebalance = "cheat", "monthly"

    def target_weights(self, data):
        full = data._panel["close"]["AAPL"]                 # bypasses the cut-off on purpose
        return pd.Series({"AAPL": 0.25 * full.iloc[-1] / full.max()})   # depends on the last (future) price


class LookAhead(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.panel = load_panel()

    def test_benchmarks(self):
        for name, cls in BENCHMARKS.items():
            with self.subTest(strategy=name):
                self.assertEqual(check_no_lookahead(cls, self.panel, DATES), [])

    def test_xgb_candidate(self):
        self.assertEqual(check_no_lookahead(XGBCandidate, self.panel, DATES[:2]), [])

    def test_detector_catches_a_cheater(self):
        self.assertNotEqual(check_no_lookahead(Cheat, self.panel, DATES), [])


if __name__ == "__main__":
    unittest.main()
