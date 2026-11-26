"""
The proposal's failure tests: broker timeout, duplicate run, missing data,
crash mid-order, invalid weights. Each must end in no trade or a correct trade.
"""

import unittest
from collections import Counter

import pandas as pd

from live.broker.fake import SimulatedCrash
from live.engine.daily import DailyEngine
from live.engine.data import PanelProvider
from tests.live_helpers import REGISTRY, make, panel, session

DAY = pd.Timestamp("2021-06-01")          # first run: buys AAPL, MSFT, SPY (3 orders)


def ids(broker):
    return Counter(o["client_order_id"] for o in broker.orders.values())


class BrokerTimeouts(unittest.TestCase):
    def test_timeout_after_accept_is_not_resent(self):
        engine, broker, ledger = make()
        broker.fail_on_submit(1, "timeout_after")
        session(broker, DAY)
        r = engine.run(DAY)
        self.assertEqual(r.status, "completed")
        self.assertEqual(len(broker.orders), 3)
        self.assertTrue(all(n == 1 for n in ids(broker).values()))

    def test_timeout_before_accept_is_retried_once(self):
        engine, broker, ledger = make()
        broker.fail_on_submit(1, "timeout_before")
        session(broker, DAY)
        self.assertEqual(engine.run(DAY).status, "completed")
        self.assertEqual(len(broker.orders), 3)

    def test_repeated_timeouts_fail_cleanly_then_rerun_completes(self):
        engine, broker, ledger = make()
        broker.fail_on_submit(1, "timeout_before")
        broker.fail_on_submit(2, "timeout_before")
        session(broker, DAY)
        r = engine.run(DAY)
        self.assertEqual(r.status, "failed")
        self.assertEqual(len(broker.orders), 2)           # the other two went through
        r2 = engine.run(DAY)                              # rerun the same day
        self.assertEqual(r2.status, "completed")
        self.assertEqual(len(broker.orders), 3)
        self.assertTrue(all(n == 1 for n in ids(broker).values()))


class DuplicateRun(unittest.TestCase):
    def test_second_run_same_day_sends_nothing(self):
        engine, broker, ledger = make()
        session(broker, DAY)
        self.assertEqual(engine.run(DAY).status, "completed")
        before = dict(broker.orders)
        self.assertEqual(engine.run(DAY).status, "duplicate")
        self.assertEqual(broker.orders, before)


class MissingData(unittest.TestCase):
    def test_stale_data_means_no_trade(self):
        engine, broker, ledger = make()
        stale = {f: df.loc[: DAY - pd.Timedelta(days=1)] for f, df in panel().items()}
        engine.provider = PanelProvider(stale)
        r = engine.run(DAY)
        self.assertEqual(r.status, "failed")
        self.assertEqual(broker.orders, {})
        self.assertTrue(any(e["kind"] == "stale_data" for e in ledger.events()))

    def test_missing_symbol_price_means_no_trade(self):
        engine, broker, ledger = make()
        gappy = {f: df.loc[:DAY].copy() for f, df in panel().items()}
        gappy["close"].loc[DAY, "MSFT"] = float("nan")
        engine.provider = PanelProvider(gappy)
        self.assertEqual(engine.run(DAY).status, "failed")
        self.assertEqual(broker.orders, {})


class CrashMidOrder(unittest.TestCase):
    def test_rerun_after_crash_sends_only_the_rest(self):
        engine, broker, ledger = make()
        broker.fail_on_submit(2, "crash")                 # dies right after the 2nd order is accepted
        session(broker, DAY)
        with self.assertRaises(SimulatedCrash):
            engine.run(DAY)
        self.assertEqual(ledger.get_run(str(DAY.date()))["status"], "started")
        broker.failures.clear()
        # A brand-new process: new engine object, same ledger and broker account.
        engine2 = DailyEngine(broker, ledger, engine.provider, engine.approved, registry=REGISTRY,
                              kill_switch_path=None)
        r = engine2.run(DAY)
        self.assertEqual(r.status, "completed")
        self.assertEqual(len(broker.orders), 3)
        self.assertTrue(all(n == 1 for n in ids(broker).values()))


class InvalidWeights(unittest.TestCase):
    def test_bad_strategy_output_means_no_trade(self):
        engine, broker, ledger = make(strategy="too_big")
        session(broker, DAY)
        r = engine.run(DAY)
        self.assertEqual(r.status, "failed")
        self.assertEqual(broker.orders, {})
        self.assertTrue(any(e["kind"] == "invalid_weights" for e in ledger.events()))


if __name__ == "__main__":
    unittest.main()
