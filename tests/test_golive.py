"""
Go-live mechanics: half-size start for 4 weeks, scale-up only if fills and the
ledger matched, and automatic rollback (or pause) when live results drift from
the paper record. Real non-holdout prices, fake broker, in-memory ledger.
"""

import unittest
from dataclasses import replace

import pandas as pd

from live.broker.fake import FakeBroker
from live.engine.daily import DailyEngine
from live.engine.data import PanelProvider
from live.ledger.db import Ledger
from live.risk.limits import DEFAULT_LIMITS
from tests.live_helpers import REGISTRY, panel, replay

START = "2021-01-04"


def engine_for(approved, broker=None, ledger=None, cash=5_000.0):
    broker = broker or FakeBroker(cash)
    if ledger is None:
        ledger = Ledger(":memory:")
        ledger.add_cash_flow("2020-12-31", cash, "initial deposit")
    e = DailyEngine(broker, ledger, PanelProvider(panel()), approved, registry=REGISTRY,
                    kill_switch_path=None, shadow_registry=REGISTRY)
    return e, broker, ledger


def invested(broker):
    a = broker.account()
    return 1 - a.cash / a.equity


def lose_shares(broker, share=0.05):
    """Shares vanish without a ledger record (a cash account can't go negative, so take holdings)."""
    eq = broker.account().equity
    sym = max(broker.holdings, key=lambda t: broker.holdings[t] * broker.marks[t])
    broker.holdings[sym] -= share * eq / broker.marks[sym]


def kinds(ledger):
    return [ev["kind"] for ev in ledger.events()]


class HalfSizeStart(unittest.TestCase):
    def test_half_for_four_weeks_then_full(self):
        e, b, l = engine_for([{"strategy": "buy_hold_index", "allocation": 1.0, "live_since": START}])
        replay(e, b, START, "2021-01-29")
        self.assertAlmostEqual(invested(b), 0.5, delta=0.03)
        replay(e, b, "2021-02-01", "2021-02-12")        # day 28 is 2021-02-01; cap phases in over ~2 days
        self.assertAlmostEqual(invested(b), 1.0, delta=0.02)
        self.assertNotIn("scale_up_blocked", kinds(l))

    def test_scale_up_blocked_after_a_reconcile_mismatch(self):
        e, b, l = engine_for([{"strategy": "buy_hold_index", "allocation": 1.0, "live_since": START}])
        replay(e, b, START, "2021-01-15")
        l.log_event("2021-01-15", "error", "reconcile_mismatch", "SPY: ledger says 1, broker says 2")
        replay(e, b, "2021-01-19", "2021-02-12")
        self.assertAlmostEqual(invested(b), 0.5, delta=0.03)
        self.assertIn("scale_up_blocked", kinds(l))

    def test_entries_without_live_since_are_unchanged(self):
        e, b, l = engine_for([{"strategy": "buy_hold_index", "allocation": 1.0}])
        replay(e, b, START, "2021-01-15")
        self.assertAlmostEqual(invested(b), 1.0, delta=0.02)


class Rollback(unittest.TestCase):
    def test_honest_momentum_go_live_in_the_2020_crash_does_not_roll_back(self):
        # Measured 2026-11-27: counting every day, the 30% turnover cap's phase-in alone made
        # this honest go-live drift 4.35 points (a false rollback). Settled days only fixes it.
        e, b, l = engine_for([{"strategy": "momentum_12_1", "allocation": 1.0, "live_since": "2020-02-03",
                               "previous": "buy_hold_index"}])
        e.limits = replace(DEFAULT_LIMITS, daily_loss_halt=1.0, drawdown_pause=1.0)   # keep it trading
        replay(e, b, "2020-02-03", "2020-05-04")
        self.assertFalse(l.get_flag("paused"))
        self.assertNotIn("rollback", kinds(l))

    def test_honest_run_never_rolls_back(self):
        # The whole 3-month window, a strategy that switches assets (trend), turnover cap on.
        e, b, l = engine_for([{"strategy": "trend_sma200", "allocation": 1.0, "live_since": START,
                               "previous": "buy_hold_index"}])
        replay(e, b, START, "2021-04-30")
        self.assertNotIn("rollback", kinds(l))

    def test_honest_replacement_never_rolls_back(self):
        # Account fully in the previous strategy, then the new one goes live and the cap phases it in.
        e, b, l = engine_for([{"strategy": "buy_hold_index", "allocation": 1.0}])
        replay(e, b, START, "2021-02-26")
        e2, _, _ = engine_for([{"strategy": "sixty_forty", "allocation": 1.0, "live_since": "2021-03-01",
                                "previous": "buy_hold_index"}], broker=b, ledger=l)
        replay(e2, b, "2021-03-01", "2021-05-28")
        self.assertNotIn("rollback", kinds(l))

    def test_drift_switches_back_to_previous_at_full_size(self):
        approved = [{"strategy": "sixty_forty", "allocation": 1.0, "live_since": START,
                     "previous": "buy_hold_index"}]
        e, b, l = engine_for(approved)
        replay(e, b, START, "2021-03-03")                # mid-month: a settled day, no fills at the open
        lose_shares(b)
        res = replay(e, b, "2021-03-04", "2021-03-31")[1]
        self.assertIn("rollback", kinds(l))
        crit = [ev for ev in l.events() if ev["kind"] == "rollback"]
        self.assertEqual(len(crit), 1)                    # fires once
        self.assertEqual(crit[0]["level"], "critical")
        last = max(res)
        self.assertIn("buy_hold_index", l.targets_on(str(last.date())))
        self.assertGreater(b.positions().get("SPY", 0) * panel()["close"].loc[last, "SPY"] / b.account().equity,
                           0.95)                          # previous strategy, full size

    def test_drift_with_no_previous_pauses_and_alerts(self):
        e, b, l = engine_for([{"strategy": "sixty_forty", "allocation": 1.0, "live_since": START}])
        replay(e, b, START, "2021-03-03")                # mid-month: a settled day, no fills at the open
        lose_shares(b)
        res = replay(e, b, "2021-03-04", "2021-03-31")[1]
        self.assertTrue(l.get_flag("paused"))
        self.assertIn("drift_pause", kinds(l))
        self.assertEqual(res[max(res)].status, "skipped")  # stays paused until a manual resume

    def test_no_drift_check_after_the_window(self):
        approved = [{"strategy": "sixty_forty", "allocation": 1.0, "live_since": START,
                     "previous": "buy_hold_index"}]
        e, b, l = engine_for(approved)
        replay(e, b, START, "2021-05-05")
        lose_shares(b)                                     # day 122: outside the 91-day window
        replay(e, b, "2021-05-06", "2021-05-14")
        self.assertNotIn("rollback", kinds(l))


if __name__ == "__main__":
    unittest.main()
