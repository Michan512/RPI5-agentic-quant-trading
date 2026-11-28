"""
Stage B checkpoint drill (proposal: "Checkpoint before B's candidates can be promoted:
every planted bad strategy rejected across at least 3 rounds").

One round sends every planted strategy (research/agent/planted.py) through the real
defences, and records which layer stopped it:
  static    research/agent/checks.py
  sandbox   container run: crashes, look-ahead test
  screen    the pre-gate rule on research + validation results
  gate1     gate 1 in the sandbox on the SYNTHETIC market (the real holdout is never
            touched by a drill)
  gate2     every available reviewer, shown the code with flattering made-up numbers;
            each reviewer must reject each plant on its own

A round is clean when every plant is stopped AND every reviewer rejected every plant.
Rounds without at least MIN_REVIEWERS reviewers are recorded but don't count. The
checkpoint is met after 3 counting rounds in a row are clean; any dirty round resets
it. The pipeline won't promote agent strategies until it is met.

Usage:  python -m research.agent.drill
"""

from __future__ import annotations

import json
import pickle
import shutil
from datetime import datetime, timezone
from pathlib import Path

from research.agent import knowledge, sandbox
from research.agent.checks import check_source
from research.agent.config import MIN_REVIEWERS
from research.agent.planted import FAKE_RESULTS, PLANTED
from research.agent.rules import screen

STATE = Path(__file__).resolve().parent / "state"
DRILL_LOG = STATE / "drills.jsonl"
ROUNDS_NEEDED = 3


def _synthetic_dir() -> Path:
    from tests.test_gate1 import PANEL       # the synthetic market used by gate 1's own tests

    d = sandbox.JOBS_DIR / "drill_synthetic"
    d.mkdir(parents=True, exist_ok=True)
    with (d / "panel.pkl").open("wb") as f:
        pickle.dump(PANEL, f, protocol=4)
    return d


def run_round(clients: list, run_job=sandbox.run_job, data_dir: Path | None = None,
              synthetic_dir: Path | None = None, log: Path | None = None) -> dict:
    from research.agent.reviewers import _ask

    log = log or DRILL_LOG
    if data_dir is None:
        from research.gates.sandbox_export import research_snapshot
        data_dir = research_snapshot()
    made_synth = synthetic_dir is None
    synthetic_dir = synthetic_dir or _synthetic_dir()
    bench = knowledge.benchmarks()
    plants = {}
    try:
        for name, src in PLANTED.items():
            layers = {}
            chk = check_source(src)
            layers["static"] = not chk.ok
            r = run_job("research", src, data_dir)
            layers["sandbox"] = not r.get("ok")
            if r.get("ok"):
                ok, _ = screen(r["results"], bench, "STOCKS" in src)
                layers["screen"] = not ok
            g = run_job("gate1", src, synthetic_dir,
                        extra={"n_trials": 50, "trial_sharpes": [], "holdout_start": "2021-01-01",
                               "gate_lookahead_dates": ["2017-06-30", "2019-03-29"]})
            layers["gate1"] = not (g.get("ok") and g["report"]["passed"])
            reviews = [_ask(c, src, FAKE_RESULTS, "drill") for c in clients]
            layers["gate2"] = bool(reviews) and all(not rv.approve for rv in reviews)
            plants[name] = {"stopped": any(layers.values()), "layers": layers,
                            "fooled_reviewers": [rv.reviewer for rv in reviews if rv.approve]}
    finally:
        if made_synth:
            shutil.rmtree(synthetic_dir, ignore_errors=True)
    counts = len(clients) >= MIN_REVIEWERS
    clean = all(p["stopped"] and not p["fooled_reviewers"] for p in plants.values())
    row = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "reviewers": len(clients),
           "counts": counts, "clean": clean, "plants": plants}
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a") as f:
        f.write(json.dumps(row) + "\n")
    return row


def checkpoint_met(log: Path | None = None) -> bool:
    log = log or DRILL_LOG
    if not log.exists():
        return False
    streak = 0
    for row in map(json.loads, log.read_text().splitlines()):
        if not row["counts"]:
            continue
        streak = streak + 1 if row["clean"] else 0
    return streak >= ROUNDS_NEEDED


def main() -> None:
    from research.agent.llm import SpendLedger
    from research.agent.reviewers import available_reviewers

    clients = available_reviewers(SpendLedger(2.0, session_id="drill"))
    row = run_round(clients)
    for name, p in row["plants"].items():
        stopped_by = [k for k, v in p["layers"].items() if v]
        print(f"{name:22s} {'stopped' if p['stopped'] else 'GOT THROUGH'} by {stopped_by or '-'}"
              + (f"; fooled: {p['fooled_reviewers']}" if p["fooled_reviewers"] else ""))
    print(f"round {'clean' if row['clean'] else 'DIRTY'}; "
          + ("counts toward the checkpoint" if row["counts"] else
             f"does NOT count ({row['reviewers']} reviewers, need {MIN_REVIEWERS})"))
    print(f"checkpoint (3 clean counting rounds in a row): {'MET' if checkpoint_met() else 'not met'}")


if __name__ == "__main__":
    main()
