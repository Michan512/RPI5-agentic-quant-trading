import sqlite3
import unittest

import pandas as pd

from live.engine.calendar import is_trading_day, trading_days
from live.ledger.db import Ledger
from research.data.loader import load_panel


class LedgerTests(unittest.TestCase):
    def test_client_order_id_is_unique(self):
        L = Ledger()
        L.start_run("2021-06-01")
        o = {"client_order_id": "20210601-portfolio-SPY-buy", "ticker": "SPY", "side": "buy", "notional": 100.0}
        L.save_plan("2021-06-01", {"s": {"SPY": 1.0}}, [o], False)
        with self.assertRaises(sqlite3.IntegrityError):
            L.save_plan("2021-06-01", {"s": {"SPY": 1.0}}, [o], False)

    def test_one_run_row_per_day(self):
        L = Ledger()
        L.start_run("2021-06-01")
        L.finish_run("2021-06-01", "completed")
        L.start_run("2021-06-01")                         # must not reopen a completed day
        self.assertEqual(L.get_run("2021-06-01")["status"], "completed")

    def test_net_deposits(self):
        L = Ledger()
        L.add_cash_flow("2021-01-01", 5000, "deposit")
        L.add_cash_flow("2021-06-01", -1000, "withdrawal")
        self.assertEqual(L.net_deposits(), 4000)


class CalendarTests(unittest.TestCase):
    def test_matches_real_trading_days(self):
        idx = load_panel(["SPY"])["close"].index
        self.assertTrue(trading_days(idx[0], idx[-1]).equals(idx))

    def test_known_days(self):
        self.assertFalse(is_trading_day("2026-11-26"))     # Thanksgiving
        self.assertFalse(is_trading_day("2026-04-03"))     # Good Friday
        self.assertFalse(is_trading_day("2026-06-19"))     # Juneteenth
        self.assertTrue(is_trading_day("2026-11-27"))


class AdapterSafety(unittest.TestCase):
    def test_refuses_without_keys(self):
        from live.broker.alpaca_adapter import AlpacaPaperBroker
        with self.assertRaises(RuntimeError):
            AlpacaPaperBroker("", "")


if __name__ == "__main__":
    unittest.main()
