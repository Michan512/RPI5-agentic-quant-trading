import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import pandas as pd

from live.risk.layer import apply_turnover_cap, guard
from live.risk.limits import DEFAULT_LIMITS
from tests.live_helpers import make, panel, replay, session

DAY = pd.Timestamp("2021-06-01")


class Guards(unittest.TestCase):
    def g(self, **kw):
        base = dict(kill_switch=False, disabled=False, paused=False, equity=5000.0,
                    equity_history=[5000.0], net_deposits=5000.0, limits=DEFAULT_LIMITS)
        return guard(**{**base, **kw}).action

    def test_ok(self):
        self.assertEqual(self.g(), "ok")

    def test_daily_loss_halt(self):
        self.assertEqual(self.g(equity=4840.0), "halt_today")       # -3.2% on the day
        self.assertEqual(self.g(equity=4900.0), "ok")               # -2%

    def test_drawdown_pause(self):
        self.assertEqual(self.g(equity=4200.0, equity_history=[5000.0, 4300.0]), "pause")   # -16% from peak

    def test_hard_stop_beats_everything_but_kill(self):
        limits = replace(DEFAULT_LIMITS, hard_stop_loss=500.0)
        self.assertEqual(self.g(equity=4400.0, limits=limits, paused=True), "hard_stop")
        self.assertEqual(self.g(equity=4400.0, limits=limits, kill_switch=True), "kill")


class TurnoverCap(unittest.TestCase):
    def test_full_switch_moves_30pct(self):
        new, capped = apply_turnover_cap(pd.Series({"SPY": 1.0}), pd.Series({"SHY": 1.0}), 0.30)
        self.assertTrue(capped)
        self.assertAlmostEqual(new["SPY"], 0.70)
        self.assertAlmostEqual(new["SHY"], 0.30)

    def test_small_change_not_capped(self):
        new, capped = apply_turnover_cap(pd.Series({"SPY": 0.9}), pd.Series({"SPY": 1.0}), 0.30)
        self.assertFalse(capped)

    def test_transition_continues_on_following_days(self):
        engine, broker, ledger = make(strategy="switcher")
        _, results = replay(engine, broker, "2021-03-24", "2021-04-14")
        w = {}
        for d in results:
            a = broker.account()
        shy = broker.positions().get("SHY", 0) * panel()["close"].loc["2021-04-14", "SHY"] / broker.account().equity
        self.assertGreater(shy, 0.95)                      # reached the target over several days
        caps = [e for e in ledger.events() if e["kind"] == "turnover_cap"]
        self.assertGreaterEqual(len(caps), 3)              # it took several capped steps


class Stops(unittest.TestCase):
    def test_hard_stop_sells_everything_and_disables(self):
        engine, broker, ledger = make(limits=replace(DEFAULT_LIMITS, hard_stop_loss=100.0))
        session(broker, DAY)
        engine.run(DAY)                                    # buys
        nxt = pd.Timestamp("2021-06-02")
        session(broker, nxt)
        broker.cash -= 200.0                               # pretend the account lost $200
        r = engine.run(nxt)
        self.assertTrue(ledger.get_flag("disabled"))
        sells = [o for o in broker.orders.values() if o["side"] == "sell"]
        self.assertEqual(len(sells), 3)
        later = pd.Timestamp("2021-06-03")
        session(broker, later)
        self.assertEqual(engine.run(later).status, "skipped")   # stays off until manual reset

    def test_drawdown_pause_needs_manual_resume(self):
        engine, broker, ledger = make()
        session(broker, DAY)
        engine.run(DAY)
        ledger.record_equity("2021-05-28", 7000.0, 0.0)    # an earlier peak far above today's value
        nxt = pd.Timestamp("2021-06-02")
        session(broker, nxt)
        self.assertEqual(engine.run(nxt).status, "halted")
        self.assertTrue(ledger.get_flag("paused"))
        later = pd.Timestamp("2021-06-03")
        session(broker, later)
        self.assertEqual(engine.run(later).status, "skipped")

    def test_kill_switch_stops_everything(self):
        with tempfile.TemporaryDirectory() as d:
            kill = Path(d) / "KILL"
            kill.write_text("stop")
            engine, broker, ledger = make(kill_switch_path=kill)
            session(broker, DAY)
            self.assertEqual(engine.run(DAY).status, "skipped")
            self.assertEqual(broker.orders, {})

    def test_half_size_start(self):
        engine, broker, ledger = make(strategy="buy_hold_index", half_size=True)
        session(broker, DAY)
        engine.run(DAY)
        (order,) = broker.orders.values()
        self.assertAlmostEqual(order["notional"], 2500.0, delta=30)


if __name__ == "__main__":
    unittest.main()
