"""
Automatic promotion and replacement on the Pi (live/promotion.py), end to end with the
fake broker on replayed 2021 prices: shadow record -> weekly gate 3 -> promotion ->
half size -> drift rollback.
"""

import unittest

import pandas as pd

from live.broker.fake import FakeBroker
from live.engine.daily import DailyEngine
from live.engine.data import PanelProvider
from live.ledger.db import Ledger
from live.promotion import effective_approved
from shared.strategy import Strategy
from tests.live_helpers import REGISTRY, panel, replay

START = "2021-01-04"


class StrongCandidate(Strategy):
    """Test fixture with hindsight (NVDA and MSFT boomed in 2021): a record that clearly passes gate 3."""
    name, rebalance = "strong_candidate", "monthly"

    def target_weights(self, data):
        return pd.Series({"NVDA": 0.25, "MSFT": 0.25, "SPY": 0.5})


REG = {**REGISTRY, "strong_candidate": StrongCandidate}
BASE = [{"strategy": "buy_hold_index", "allocation": 1.0}]


def make(approved=BASE, ledger=None, broker=None, eligible=frozenset({"strong_candidate", "sixty_forty_x"}),
         shadows=("strong_candidate", "sixty_forty")):
    broker = broker or FakeBroker(5_000.0)
    if ledger is None:
        ledger = Ledger(":memory:")
        ledger.add_cash_flow("2020-12-31", 5_000.0, "initial deposit")
    e = DailyEngine(broker, ledger, PanelProvider(panel()), approved, registry=REG, kill_switch_path=None,
                    shadows=list(shadows), shadow_registry=REG, promotion_eligible=set(eligible))
    return e, broker, ledger


def kinds(ledger):
    return [ev["kind"] for ev in ledger.events()]


class Promotion(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.e, cls.b, cls.l = make()
        cls.eq, cls.res = replay(cls.e, cls.b, START, "2021-04-30")     # promoted 9 Apr (3-month gate 3), half size until ~10 May

    def test_promoted_after_three_months_of_paper_record(self):
        p = self.l.get_value("promotion")
        self.assertIsNotNone(p)
        self.assertEqual(p["strategy"], "strong_candidate")
        self.assertEqual(p["previous"], "buy_hold_index")
        promoted_on = pd.Timestamp(p["promoted_on"])
        self.assertGreaterEqual((promoted_on - pd.Timestamp(START)).days / 30.44, 3.0)
        self.assertEqual(promoted_on.dayofweek, 4)                     # a Friday: last trading day of the week
        self.assertIn("promotion", kinds(self.l))
        crit = [ev for ev in self.l.events() if ev["kind"] == "promotion"]
        self.assertEqual(crit[0]["level"], "critical")
        self.assertIn("PAPER", crit[0]["message"])

    def test_trades_at_half_size_after_promotion(self):
        last = max(self.res)
        targets = self.l.targets_on(str(last.date()))
        self.assertIn("strong_candidate", targets)
        a = self.b.account()
        nvda = self.b.positions().get("NVDA", 0) * panel()["close"].loc[last, "NVDA"] / a.equity
        self.assertAlmostEqual(nvda, 0.125, delta=0.03)                # 25% x half size

    def test_benchmarks_and_lagging_candidates_are_never_promoted(self):
        self.assertEqual(len([k for k in kinds(self.l) if k == "promotion"]), 1)

    def test_owner_release_wins(self):
        l2 = Ledger(":memory:")
        l2.set_value("promotion", self.l.get_value("promotion"))
        new_release = [{"strategy": "sixty_forty", "allocation": 1.0}]
        self.assertEqual(effective_approved(BASE, l2)[0]["strategy"], "strong_candidate")
        self.assertEqual(effective_approved(new_release, l2, "2021-09-01")[0]["strategy"], "sixty_forty")
        self.assertIsNone(l2.get_value("promotion"))
        self.assertIn("promotion_cleared", kinds(l2))


class PromotionGuards(unittest.TestCase):
    def test_lagging_candidate_is_not_promoted(self):
        e, b, l = make(eligible={"sixty_forty"}, shadows=("sixty_forty",))
        replay(e, b, START, "2021-08-31")
        self.assertIsNone(l.get_value("promotion"))

    def test_no_promotion_while_paused(self):
        e, b, l = make()
        replay(e, b, START, "2021-03-31")
        l.set_flag("paused", True)
        replay(e, b, "2021-04-01", "2021-05-31")
        self.assertIsNone(l.get_value("promotion"))

    def test_drift_after_promotion_rolls_back_to_previous(self):
        e, b, l = make()
        replay(e, b, START, "2021-04-21")
        self.assertIsNotNone(l.get_value("promotion"))
        sym = max(b.holdings, key=lambda t: b.holdings[t] * b.marks[t])
        b.holdings[sym] -= 0.05 * b.account().equity / b.marks[sym]     # shares vanish on a settled day
        _, res = replay(e, b, "2021-04-22", "2021-05-20")
        self.assertIn("rollback", kinds(l))
        self.assertEqual(len([k for k in kinds(l) if k == "promotion"]), 1)   # not re-promoted after rollback
        self.assertIn("buy_hold_index", l.targets_on(str(max(res).date())))

    def test_no_second_promotion_inside_the_drift_window(self):
        class Stronger(StrongCandidate):
            name = "stronger_candidate"

            def target_weights(self, data):
                return pd.Series({"NVDA": 0.25, "TSLA": 0.25, "SPY": 0.5})
        REG["stronger_candidate"] = Stronger
        try:
            e, b, l = make(eligible={"strong_candidate", "stronger_candidate"},
                           shadows=("strong_candidate", "stronger_candidate"))
            replay(e, b, START, "2021-09-30")
            self.assertEqual(len([k for k in kinds(l) if k == "promotion"]), 1)
        finally:
            REG.pop("stronger_candidate", None)


if __name__ == "__main__":
    unittest.main()
