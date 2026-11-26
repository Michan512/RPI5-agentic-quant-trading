"""
Promotion gate 1, tested on SYNTHETIC prices only, so the real holdout stays unopened.

The synthetic market: one common market factor plus a fixed drift per stock and
a little noise. The broad index is the average stock; the bond ETF is flat.
A momentum rule should find the high-drift stocks and pass; a do-nothing
strategy must fail.
"""

import json
import math
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from research.gates import gate1
from research.gates.dsr import deflated_sharpe, expected_max_sharpe, probabilistic_sharpe
from research.strategies.momentum import Momentum
from shared.strategy import Strategy
from shared.universe import ALL_SYMBOLS, STOCKS

HOLDOUT = "2021-01-01"
LOOKAHEAD = ("2017-06-30", "2019-03-29")


def synthetic_panel(seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2014-01-01", "2023-12-29")
    n = len(idx)
    market = rng.normal(0.0003, 0.009, n)
    drifts = np.linspace(-0.0004, 0.0016, len(STOCKS))          # last stocks drift up strongly
    rets = {s: market + drifts[i] + rng.normal(0, 0.004, n) for i, s in enumerate(STOCKS)}
    rets["SPY"] = np.mean([rets[s] for s in STOCKS], axis=0)
    rets["SHY"] = np.full(n, 0.0001)
    rets["^VIX"] = rng.normal(0, 0.02, n)
    for s in ALL_SYMBOLS:                                       # other ETFs: market-like, no edge
        if s not in rets:
            rets[s] = market * 0.5 + rng.normal(0.0001, 0.005, n)
    close = pd.DataFrame({s: 100 * np.exp(np.cumsum(rets[s])) for s in ALL_SYMBOLS}, index=idx)
    open_ = close.shift(1).fillna(close.iloc[0])
    return {"close": close, "open": open_, "high": np.maximum(open_, close) * 1.002,
            "low": np.minimum(open_, close) * 0.998,
            "volume": pd.DataFrame(1e6, index=idx, columns=list(ALL_SYMBOLS))}


class StayInCash(Strategy):
    name, rebalance = "stay_in_cash", "monthly"

    def target_weights(self, data):
        return pd.Series(dtype=float)


class NamesATicker(Strategy):
    name, rebalance = "names_a_ticker", "monthly"

    def target_weights(self, data):
        return pd.Series({"AAPL": 0.25})


def run(cls, log):
    return gate1.run_gate1(cls, panel=PANEL, holdout_start=HOLDOUT, lookahead_dates=LOOKAHEAD,
                           n_trials=1, trial_sharpes=[], log=log)


PANEL = synthetic_panel()


def checks(report):
    return {c.name: c for c in report.checks}


class Gate1(unittest.TestCase):
    def test_good_rule_passes_every_check(self):
        with tempfile.TemporaryDirectory() as d:
            r = run(Momentum, Path(d) / "log.jsonl")
            failed = [(c.name, c.value, c.threshold) for c in r.checks if not c.passed]
            self.assertTrue(r.passed, failed)
            self.assertIn("stock_picker_beats_equal_weight", checks(r))

    def test_do_nothing_fails(self):
        with tempfile.TemporaryDirectory() as d:
            r = run(StayInCash, Path(d) / "log.jsonl")
            self.assertFalse(r.passed)
            self.assertFalse(checks(r)["beats_bank_rate"].passed)
            self.assertFalse(checks(r)["beats_buy_and_hold"].passed)

    def test_named_ticker_fails_rules_check(self):
        with tempfile.TemporaryDirectory() as d:
            r = run(NamesATicker, Path(d) / "log.jsonl")
            self.assertFalse(checks(r)["rules_only_no_ticker_names"].passed)

    def test_one_attempt_per_version_and_logged(self):
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "log.jsonl"
            run(StayInCash, log)
            with self.assertRaises(gate1.AlreadyAttempted):
                run(StayInCash, log)
            rows = [json.loads(l) for l in log.read_text().splitlines()]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["strategy"], "stay_in_cash")

    def test_real_benchmarks_have_no_ticker_literals(self):
        from research.strategies import BENCHMARKS, ETF_ROUND1
        from research.strategies.xgb_candidate import XGBCandidate
        for cls in list(BENCHMARKS.values()) + list(ETF_ROUND1.values()) + [XGBCandidate]:
            self.assertEqual(gate1.ticker_literals(cls), [], cls.name)


class DeflatedSharpe(unittest.TestCase):
    def test_one_trial_means_no_luck_penalty(self):
        self.assertEqual(expected_max_sharpe(1, 0.1), 0.0)

    def test_more_trials_raise_the_bar(self):
        self.assertLess(expected_max_sharpe(10, 0.05), expected_max_sharpe(100, 0.05))
        r = np.random.default_rng(0).normal(0.0008, 0.01, 750)
        few = deflated_sharpe(r, 2, [0.01, 0.03])["dsr"]
        many = deflated_sharpe(r, 200, [0.01, 0.03])["dsr"]
        self.assertGreater(few, many)

    def test_matches_formula(self):
        # Normal returns (skew 0, kurtosis 3): PSR = Phi(SR * sqrt(T-1) / sqrt(1 + SR^2 / 2)).
        from statistics import NormalDist
        sr, T = 0.05, 500
        expected = NormalDist().cdf(sr * math.sqrt(T - 1) / math.sqrt(1 + 0.5 * sr ** 2))
        self.assertAlmostEqual(probabilistic_sharpe(sr, 0.0, T, 0.0, 3.0), expected, places=12)


if __name__ == "__main__":
    unittest.main()
