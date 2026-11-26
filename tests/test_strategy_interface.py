import unittest

import pandas as pd

from shared.strategy import InvalidWeights, PriceView, is_rebalance_day, validate_weights
from tests.helpers import synthetic_panel


class ValidateWeights(unittest.TestCase):
    def test_valid(self):
        w = validate_weights(pd.Series({"AAPL": 0.25, "MSFT": 0.25, "SPY": 0.5}))
        self.assertAlmostEqual(w.sum(), 1.0)

    def test_stock_cap(self):
        with self.assertRaises(InvalidWeights):
            validate_weights(pd.Series({"AAPL": 0.26}))

    def test_etf_may_be_100pct(self):
        validate_weights(pd.Series({"SPY": 1.0}))

    def test_sector_etf_capped_like_a_stock(self):
        validate_weights(pd.Series({"XLK": 0.25, "XLF": 0.25, "SHY": 0.5}))
        with self.assertRaises(InvalidWeights):
            validate_weights(pd.Series({"XLK": 0.30}))

    def test_asset_class_etf_may_be_100pct(self):
        validate_weights(pd.Series({"GLD": 1.0}))

    def test_sum_above_one(self):
        with self.assertRaises(InvalidWeights):
            validate_weights(pd.Series({"SPY": 0.9, "AAPL": 0.2}))

    def test_negative(self):
        with self.assertRaises(InvalidWeights):
            validate_weights(pd.Series({"AAPL": -0.1}))

    def test_outside_universe(self):
        with self.assertRaises(InvalidWeights):
            validate_weights(pd.Series({"GME": 0.1}))

    def test_empty_means_cash(self):
        self.assertTrue(validate_weights(pd.Series(dtype=float)).empty)


class PriceViewCutoff(unittest.TestCase):
    def test_no_rows_after_asof(self):
        p = synthetic_panel()
        T = p["close"].index[100]
        v = PriceView(p, T)
        for f in ("open", "high", "low", "close", "volume"):
            self.assertEqual(v.field(f).index[-1], T)
            self.assertEqual(len(v.field(f)), 101)


class RebalanceCalendar(unittest.TestCase):
    def test_month_end(self):
        idx = pd.bdate_range("2020-01-27", "2020-02-05")
        flags = [is_rebalance_day(idx, i, "monthly") for i in range(len(idx))]
        self.assertEqual([d for d, f in zip(idx, flags) if f], [pd.Timestamp("2020-01-31")])


if __name__ == "__main__":
    unittest.main()
