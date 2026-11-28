"""
Promotion pipeline for agent submissions (proposal, "Promotion gates"; automatic:
"you are notified, not asked").

  gate 1   fixed checks on the holdout, run INSIDE the sandbox with the full snapshot.
           One attempt per exact source. Appended to research/gates/gate_log.jsonl.
  checkpoint  agent strategies can't be promoted until the stage B drill has had 3 clean
           rounds (research/agent/drill.py). Until then a gate 1 pass waits in
           state/pending.jsonl; `python -m research.agent.pipeline --resume-pending`
           continues them once it's met.
  gate 2   reviewer agents from other providers (research/agent/reviewers.py)
  promote  the code is filed as research/strategies/agent/<name>.py, registered, and
           added to live/shadow.json. That starts its gate 3 paper period on the Pi
           once the owner commits and tags a live-v* release (the Pi only pulls).
           Going live later still needs gate 3 (6 months of paper record).

The agent never sees anything from this module: no gate results, no review text.
Outcomes go to research/agent/state/pipeline.jsonl and, for promotions and pauses,
to the owner's alert channel.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from research.agent import sandbox
from research.agent.checks import check_source
from research.agent.llm import SpendLedger
from research.agent.reviewers import available_reviewers, review

REPO = Path(__file__).resolve().parents[2]
STATE = Path(__file__).resolve().parent / "state"
PIPELINE_LOG = STATE / "pipeline.jsonl"
PENDING = STATE / "pending.jsonl"          # passed gate 1 while the drill checkpoint wasn't met yet
GATE_LOG = REPO / "research" / "gates" / "gate_log.jsonl"
AGENT_DIR = REPO / "research" / "strategies" / "agent"
AGENT_REGISTRY = AGENT_DIR / "registry.json"
SHADOW = REPO / "live" / "shadow.json"
REVIEW_BUDGET_USD = 2.0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _record(row: dict) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    with PIPELINE_LOG.open("a") as f:
        f.write(json.dumps({"ts": _now(), **row}, default=str) + "\n")


def _notify(msg: str) -> None:
    try:
        from live.notify import Notifier
        Notifier().send(msg)
    except Exception:
        pass


def already_attempted(source_sha: str, log: Path = GATE_LOG) -> bool:
    if not log.exists():
        return False
    return any(json.loads(l).get("source_sha") == source_sha for l in log.read_text().splitlines() if l.strip())


def run_gate1(name: str, src: str, trial_id: int, run_job=sandbox.run_job, log: Path = GATE_LOG) -> dict:
    from research.gates.gate1 import _trial_sharpes_daily
    from research.gates.sandbox_export import full_snapshot
    from research.trials.log import trial_count

    sha = check_source(src).source_sha
    if already_attempted(sha, log):
        return {"ok": False, "stage": "already_attempted", "error": "this exact code already took gate 1"}
    r = run_job("gate1", src, full_snapshot(),
                extra={"n_trials": max(trial_count(), 1), "trial_sharpes": _trial_sharpes_daily()})
    row = {"timestamp": _now(), "author": "agent", "trial_id": trial_id, "source_sha": sha, "strategy": name}
    if r.get("ok"):
        row.update(r["report"])
    else:
        row.update({"passed": False, "error": f"{r.get('stage')}: {r.get('error')}"})
    with log.open("a") as f:                              # every attempt is logged, pass or fail
        f.write(json.dumps(row, default=str) + "\n")
    return {"ok": bool(r.get("ok")), "passed": bool(row.get("passed")), "row": row}


def promote(name: str, src: str, trial_id: int, gate1_row: dict, reviews: list) -> Path:
    AGENT_DIR.mkdir(parents=True, exist_ok=True)
    path = AGENT_DIR / f"{name}.py"
    header = (f"# Agent-written strategy, promoted {_now()[:10]}: trial {trial_id}, gate 1 version "
              f"{gate1_row.get('version')}, gate 2 approved by {', '.join(r.reviewer for r in reviews)}.\n"
              f"# Paper period (gate 3) starts when this is deployed to the Pi. Do not edit: any change is a new version.\n")
    path.write_text(header + src, encoding="utf-8")
    reg = json.loads(AGENT_REGISTRY.read_text()) if AGENT_REGISTRY.exists() else []
    if name not in reg:
        reg.append(name)
    AGENT_REGISTRY.write_text(json.dumps(reg, indent=1) + "\n")
    shadows = json.loads(SHADOW.read_text()) if SHADOW.exists() else []
    if name not in shadows:
        shadows.append(name)
        SHADOW.write_text(json.dumps(shadows) + "\n")
    return path


def submit(trial_id: int, name: str, src: str, results: dict, run_job=sandbox.run_job, clients=None,
           gate_log: Path = GATE_LOG, notify=_notify, checkpoint=None) -> dict:
    g1 = run_gate1(name, src, trial_id, run_job=run_job, log=gate_log)
    if not g1.get("passed"):
        out = {"trial_id": trial_id, "strategy": name, "status": "gate1_failed",
               "detail": g1.get("error") or [c["name"] for c in g1["row"].get("checks", []) if not c["passed"]]}
        _record(out)
        return out
    if checkpoint is None:
        from research.agent.drill import checkpoint_met
        checkpoint = checkpoint_met
    if not checkpoint():
        STATE.mkdir(parents=True, exist_ok=True)
        with PENDING.open("a") as f:
            f.write(json.dumps({"ts": _now(), "trial_id": trial_id, "strategy": name, "src": src,
                                "results": results, "gate1_row": g1["row"], "done": False}, default=str) + "\n")
        out = {"trial_id": trial_id, "strategy": name, "status": "waiting_for_checkpoint"}
        _record(out)
        notify(f"Stage B: {name} passed gate 1 but waits for the drill checkpoint (3 clean rounds of "
               f"python -m research.agent.drill), then python -m research.agent.pipeline --resume-pending")
        return out
    return _gate2_and_promote(trial_id, name, src, results, g1["row"], clients, notify)


def _gate2_and_promote(trial_id, name, src, results, gate1_row, clients, notify) -> dict:
    if clients is None:
        clients = available_reviewers(SpendLedger(REVIEW_BUDGET_USD, session_id=f"review-{trial_id}"))
    g2 = review(name, src, results, clients, notify=notify)
    if not g2.passed:
        out = {"trial_id": trial_id, "strategy": name, "status": f"gate2_{g2.status}", "detail": g2.detail,
               "reviews": [r.__dict__ for r in g2.reviews]}
        _record(out)
        if g2.status == "not_enough_reviewers":
            notify(f"Stage B: {name} passed gate 1 but is waiting for reviewers: {g2.detail}")
        return out
    path = promote(name, src, trial_id, gate1_row, g2.reviews)
    out = {"trial_id": trial_id, "strategy": name, "status": "promoted_to_paper", "file": str(path)}
    _record(out)
    notify(f"Stage B: {name} (trial {trial_id}) passed gates 1 and 2 and was added to the paper-trading "
           f"comparisons. Commit and tag a live-v* release to start its paper period on the Pi.")
    return out


def resume_pending(clients=None, notify=_notify, checkpoint=None) -> list[dict]:
    """Continue gate-1 passes that were waiting for the drill checkpoint."""
    if checkpoint is None:
        from research.agent.drill import checkpoint_met
        checkpoint = checkpoint_met
    if not PENDING.exists() or not checkpoint():
        return []
    rows = [json.loads(l) for l in PENDING.read_text().splitlines() if l.strip()]
    outs = []
    for row in rows:
        if row["done"]:
            continue
        outs.append(_gate2_and_promote(row["trial_id"], row["strategy"], row["src"], row["results"],
                                       row["gate1_row"], clients, notify))
        row["done"] = True
    PENDING.write_text("".join(json.dumps(r, default=str) + "\n" for r in rows))
    return outs


if __name__ == "__main__":
    import sys
    if "--resume-pending" in sys.argv:
        for o in resume_pending():
            print(o["strategy"], o["status"])
    else:
        print(__doc__)
