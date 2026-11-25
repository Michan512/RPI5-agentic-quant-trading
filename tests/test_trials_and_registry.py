import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from xgboost import XGBClassifier

from research.strategies.buy_hold import BuyHold
from research.trials import log, model_registry


class TrialLog(unittest.TestCase):
    def test_rejects_holdout_and_counts(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(log, "TRIALS_FILE", Path(d) / "t.jsonl"):
            with self.assertRaises(ValueError):
                log.log_trial(BuyHold(), "x", {"holdout": {"cagr": 1}})
            self.assertEqual(log.log_trial(BuyHold(), "x", {"research": {"cagr": 0.1}}), 1)
            self.assertEqual(log.log_trial(BuyHold(), "y", {"validation": {"cagr": 0.1}}), 2)
            self.assertEqual(log.trial_count(), 2)


class Registry(unittest.TestCase):
    def test_versions_never_overwrite_and_need_approval(self):
        X, y = np.random.default_rng(0).random((50, 3)), np.arange(50) % 2
        m = XGBClassifier(n_estimators=2).fit(X, y)
        with tempfile.TemporaryDirectory() as d, mock.patch.object(model_registry, "MODELS_DIR", Path(d)):
            self.assertEqual(model_registry.save_candidate("m", m, {}), "v0001")
            self.assertEqual(model_registry.save_candidate("m", m, {}), "v0002")
            self.assertTrue(all(v["status"] == "candidate" for v in model_registry.list_versions("m")))
            with self.assertRaises(LookupError):
                model_registry.load_approved("m")
            model_registry.approve("m", "v0001", "test", "unit test")
            _, meta = model_registry.load_approved("m")
            self.assertEqual(meta["version"], "v0001")


if __name__ == "__main__":
    unittest.main()
