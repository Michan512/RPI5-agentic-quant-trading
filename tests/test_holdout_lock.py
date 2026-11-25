import re
import unittest
from pathlib import Path

from research.data import splits
from research.data.loader import HoldoutAccessError, load_panel

REPO = Path(__file__).resolve().parents[1]


class HoldoutLock(unittest.TestCase):
    def test_default_load_stops_before_holdout(self):
        p = load_panel(["SPY", "AAPL"])
        self.assertLess(p["close"].index.max(), splits.HOLDOUT_START)

    def test_non_gate_caller_is_refused(self):
        with self.assertRaises(HoldoutAccessError):
            load_panel(["SPY"], include_holdout=True)

    def test_gate_caller_is_allowed(self):
        code = "from research.data.loader import load_panel\np = load_panel(['SPY'], include_holdout=True)"
        ns = {"__name__": "research.gates.fake_gate"}
        exec(compile(code, "research/gates/fake_gate.py", "exec"), ns)
        self.assertGreaterEqual(ns["p"]["close"].index.max(), splits.HOLDOUT_START)

    def test_no_code_bypasses_the_loader(self):
        """Only research/data and research/gates may touch the raw files or ask for holdout."""
        allowed = [REPO / "research" / "data", REPO / "research" / "gates"]
        pattern = re.compile(r"include_holdout\s*=\s*True|data[/\\. ]+raw|RAW_DIR|read_csv")
        offenders = []
        files = [f for d in ("research", "shared", "live") for f in (REPO / d).rglob("*.py")]
        for f in files:
            if any(a in f.parents for a in allowed):
                continue
            if pattern.search(f.read_text(encoding="utf-8")):
                offenders.append(str(f.relative_to(REPO)))
        self.assertEqual(offenders, [], f"files reading raw data / holdout directly: {offenders}")


if __name__ == "__main__":
    unittest.main()
