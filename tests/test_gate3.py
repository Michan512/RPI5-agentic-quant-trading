"""
Gate 3 (paper period) and the shadow books it judges. Real non-holdout prices,
fake broker, in-memory ledger.
"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from live import gate3
from live.ledger.db import Ledger
from shared.strategy import Strategy
from tests.live_helpers import REGISTRY, make, panel, replay

START, END = "2021-01-04", "2021-12-31"


class Explodes(Strategy):
    name, rebalance = "explodes", "monthly"

    def target_weights(self, data):
        raise RuntimeError("boom")


class ShortBondsOnly(Strategy):
    """A deliberately weak yardstick (short Treasuries; about -0.5% in 2021)."""
    name, rebalance = "short_bonds_only", "monthly"

    def target_weights(self, data):
        return pd.Series({"SHY": 1.0})


SHADOW_REG = {**REGISTRY, "explodes": Explodes, "short_bonds_only": ShortBondsOnly}


def make_with_shadows(shadows, **kw):
    return make(strategy="three_way", shadows=shadows, shadow_registry=SHADOW_REG, **kw)


class ShadowBooks(unittest.TestCase):
    def test_shadows_are_recorded_and_never_change_trading(self):
        e0, b0, _ = make(strategy="three_way")
        eq0, _ = replay(e0, b0, START, "2021-03-31")
        e1, b1, l1 = make_with_shadows(["sixty_forty", "trend_sma200", "explodes"])
        eq1, res1 = replay(e1, b1, START, "2021-03-31")
        pd.testing.assert_series_equal(eq0, eq1)                     # trading identical
        self.assertTrue(all(r.status == "completed" for r in res1.values()))
        rec = l1.recorded_targets("sixty_forty")
        self.assertEqual(len(rec), len(eq1))                         # one record per trading day
        self.assertEqual(rec[min(rec)], {"SPY": 0.6, "IEF": 0.4})
        self.assertEqual(l1.recorded_targets("explodes"), {})        # failed shadow: logged, skipped
        kinds = {ev["kind"] for ev in l1.events_between("2021-01-01", "2021-12-31")}
        self.assertIn("shadow_failed", kinds)

    def test_shadows_still_recorded_when_trading_is_stopped(self):
        with tempfile.TemporaryDirectory() as d:
            kill = Path(d) / "KILL"
            kill.write_text("stop")
            e, b, l = make_with_shadows(["sixty_forty"], kill_switch_path=kill)
            _, res = replay(e, b, START, "2021-01-08")
            self.assertTrue(all(r.status == "skipped" for r in res.values()))
            self.assertEqual(len(l.recorded_targets("sixty_forty")), 5)

    def test_approved_strategy_is_not_duplicated_as_shadow(self):
        e, _, _ = make_with_shadows(["three_way", "sixty_forty"])
        self.assertEqual(e.shadows, ["sixty_forty"])


class Gate3(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        e, b, cls.ledger = make_with_shadows(["sixty_forty", "trend_sma200"])
        replay(e, b, START, END)

    def report(self, name, ledger=None, **kw):
        return gate3.evaluate(name, ledger or self.ledger, panel(), SHADOW_REG, **kw)

    def test_honest_record_matches_backtest(self):
        r = self.report("sixty_forty")
        c = {x.name: x for x in r.checks}
        self.assertEqual(c["target_match"].value, 1.0)
        self.assertLess(c["return_gap_vs_backtest"].value, 1e-9)
        self.assertTrue(c["long_enough"].passed)                     # ~12 months >= 6
        # 2021: 60/40 lagged SPY, so it fails on performance, not on drift.
        self.assertFalse(c["beats_buy_and_hold"].passed)
        self.assertEqual(r.verdict, "fail")

    def test_pass_when_every_check_passes(self):
        # 2021: trend held the index all year (about +28%), far above short bonds and 5%.
        with mock.patch.object(gate3.T, "BENCHMARK", "short_bonds_only"):
            r = self.report("trend_sma200")
        failed = [(c.name, c.value, c.threshold) for c in r.checks if not c.passed]
        self.assertEqual(r.verdict, "pass", failed)

    def test_tampered_record_fails_on_target_match(self):
        l = Ledger(":memory:")
        recs = self.ledger.recorded_targets("sixty_forty")
        for d, w in recs.items():
            l.save_shadow_targets(d, {"sixty_forty": w})
        l.save_shadow_targets("2021-06-30", {"sixty_forty": {"SPY": 1.0}})  # a day the Pi got it wrong
        r = self.report("sixty_forty", ledger=l)
        c = {x.name: x for x in r.checks}
        self.assertFalse(c["target_match"].passed)
        self.assertIn("2021-06-30", c["target_match"].detail)
        self.assertEqual(r.verdict, "fail")

    def test_short_record_is_not_yet(self):
        r = self.report("sixty_forty", end="2021-03-31")
        self.assertEqual(r.verdict, "not_yet")

    def test_replacement_needs_three_months_and_must_beat_live(self):
        r = self.report("trend_sma200", replacing="sixty_forty", end="2021-02-26")
        self.assertEqual(r.verdict, "not_yet")
        self.assertIn("beats_live_strategy", {c.name for c in r.checks})

    def test_no_record(self):
        self.assertEqual(self.report("low_vol_252").verdict, "not_yet")


class LiveDataHolidayRows(unittest.TestCase):
    """Found 2026-11-26 while checking the shadow books on real data: the live feed had
    Memorial Day and Labor Day rows with no tradable prices, which sent low-vol rules to cash."""

    def test_rows_without_any_tradable_price_are_dropped(self):
        from live.engine.data import drop_non_trading_rows
        from research.strategies import BENCHMARKS
        from shared.strategy import PriceView
        p = panel()
        end = p["close"].index.searchsorted(pd.Timestamp("2021-06-30"), side="right")
        clean = {f: df.iloc[:end] for f, df in p.items()}
        holiday = pd.Timestamp("2021-05-31")                       # Memorial Day: not in the data
        self.assertNotIn(holiday, clean["close"].index)
        dirty = {}
        for f, df in clean.items():
            row = pd.DataFrame(float("nan"), index=[holiday], columns=df.columns)
            if "^VIX" in row.columns:
                row["^VIX"] = 20.0                                 # a data-only series still reports
            dirty[f] = pd.concat([df, row]).sort_index()
        d = pd.Timestamp("2021-06-30")
        low_vol = BENCHMARKS["low_vol_252"]
        self.assertTrue(low_vol().target_weights(PriceView(dirty, d)).empty)   # the bug
        fixed = drop_non_trading_rows(dirty)
        self.assertNotIn(holiday, fixed["close"].index)
        pd.testing.assert_series_equal(low_vol().target_weights(PriceView(fixed, d)),
                                       low_vol().target_weights(PriceView(clean, d)))


if __name__ == "__main__":
    unittest.main()
