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
# Hypothesis / lesson notes added after the fact for trials logged before those fields
# existed (trials.jsonl itself is append-only and never rewritten).
ANNOTATIONS_FILE = Path(__file__).resolve().parent / "annotations.json"
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
    trials = [json.loads(line) for line in TRIALS_FILE.read_text().splitlines() if line.strip()]
    notes = json.loads(ANNOTATIONS_FILE.read_text(encoding="utf-8")) if ANNOTATIONS_FILE.exists() else {}
    for t in trials:
        for k, v in notes.get(str(t["trial_id"]), {}).items():
            t.setdefault(k, v)
    return trials


def trial_count() -> int:
    return len(read_trials())


def log_trial(strategy, idea: str, results: dict[str, dict], notes: str = "",
              extra: dict | None = None, hypothesis: str = "", lesson: str = "") -> int:
    """Append one trial. `results` maps period name ('research'/'validation') -> metrics."""
    return log_trial_record(
        name=strategy.name, class_path=f"{type(strategy).__module__}.{type(strategy).__name__}",
        idea=idea, params=strategy.params(), source_sha=_source_hash(type(strategy)), results=results,
        notes=notes, extra=extra, hypothesis=hypothesis, lesson=lesson)


def log_trial_record(*, name: str, class_path: str, idea: str, params: dict, source_sha: str,
                     results: dict[str, dict], notes: str = "", extra: dict | None = None,
                     hypothesis: str = "", lesson: str = "", author: str = "human") -> int:
    """Append one trial from plain fields. Used for agent-written strategies, which are never
    imported on the host (their code only ever runs inside the sandbox)."""
    bad = set(results) - set(PERIODS)
    if bad:
        raise ValueError(f"only {sorted(PERIODS)} results may be logged, got {sorted(bad)}")
    trials = read_trials()
    record = {
        "trial_id": len(trials) + 1,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "strategy": name,
        "class": class_path,
        "author": author,
        "idea": idea,
        "hypothesis": hypothesis,
        "lesson": lesson,
        "params": params,
        "code_version": {**_git_version(), "strategy_source_sha256": source_sha},
        "engine_settings": settings.as_dict(),
        "periods": {k: [str(PERIODS[k][0].date()), str(PERIODS[k][1].date())] for k in results},
        "results": results,
        "caveats": [SURVIVORSHIP_NOTE],
        "notes": notes,
        **({"extra": extra} if extra else {}),
    }
    with TRIALS_FILE.open("a") as f:
        f.write(json.dumps(record, default=float) + "\n")
    return record["trial_id"]
