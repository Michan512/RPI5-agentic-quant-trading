"""
Automatic trial log: one JSON line per candidate strategy evaluated.

Every candidate backtest is recorded here (good or bad), with the idea, code
version, settings and results on research and validation. The total trial count
later feeds the overfitting penalty in the promotion gate. Benchmarks are not
trials and are reported separately (research/trials/benchmarks.md).

Holdout results can never be logged here: only the periods in
research/data/splits.PERIODS are accepted.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from research.data.splits import PERIODS
from research.engine import settings
from shared.universe import SURVIVORSHIP_NOTE

TRIALS_FILE = Path(__file__).resolve().parent / "trials.jsonl"
REPO_ROOT = Path(__file__).resolve().parents[2]


def _git_version() -> dict:
    def git(*args):
        try:
            return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True,
                                  text=True, timeout=10).stdout.strip()
        except Exception:
            return ""
    return {"commit": git("rev-parse", "--short", "HEAD") or None,
            "dirty": bool(git("status", "--porcelain"))}


def _source_hash(obj) -> str:
    src = inspect.getsource(inspect.getmodule(obj))
    return hashlib.sha256(src.encode()).hexdigest()[:12]


def read_trials() -> list[dict]:
    if not TRIALS_FILE.exists():
        return []
    return [json.loads(line) for line in TRIALS_FILE.read_text().splitlines() if line.strip()]


def trial_count() -> int:
    return len(read_trials())


def log_trial(strategy, idea: str, results: dict[str, dict], notes: str = "",
              extra: dict | None = None) -> int:
    """Append one trial. `results` maps period name ('research'/'validation') -> metrics."""
    bad = set(results) - set(PERIODS)
    if bad:
        raise ValueError(f"only {sorted(PERIODS)} results may be logged, got {sorted(bad)}")
    trials = read_trials()
    record = {
        "trial_id": len(trials) + 1,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "strategy": strategy.name,
        "class": f"{type(strategy).__module__}.{type(strategy).__name__}",
        "idea": idea,
        "params": strategy.params(),
        "code_version": {**_git_version(), "strategy_source_sha256": _source_hash(type(strategy))},
        "engine_settings": settings.as_dict(),
        "periods": {k: [str(PERIODS[k][0].date()), str(PERIODS[k][1].date())] for k in results},
        "results": results,
        "caveats": [SURVIVORSHIP_NOTE],
        "notes": notes,
        **({"extra": extra} if extra else {}),
    }
    with TRIALS_FILE.open("a") as f:
        f.write(json.dumps(record) + "\n")
    return record["trial_id"]
