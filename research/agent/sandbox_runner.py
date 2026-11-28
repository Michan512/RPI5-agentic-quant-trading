"""
Runs INSIDE the sandbox container (trusted code; the strategy it loads is not).

Reads /job/job.json, loads /job/strategy.py, and prints exactly one result line:
    @@RESULT-<nonce>@@ {json}
The nonce comes from job.json and is read before the strategy is imported. The
static checks forbid the strategy from printing or opening files, so it can't forge
the line.

Modes:
  research  look-ahead test, then backtests on the research and validation periods
            (/data/panel.pkl has no holdout rows)
  gate1     promotion gate 1 on the full snapshot (holdout included); the host
            appends the report to the gate log, and the agent never sees it
"""

from __future__ import annotations

import importlib.util
import json
import pickle
import sys
import time
import traceback
from dataclasses import asdict

JOB = "/job"


def _emit(nonce: str, payload: dict) -> None:
    sys.stdout.write(f"@@RESULT-{nonce}@@ " + json.dumps(payload, default=_json_default) + "\n")
    sys.stdout.flush()


def _json_default(o):
    try:
        return float(o)
    except (TypeError, ValueError):
        return str(o)


def _load_strategy(path: str):
    from shared.strategy import Strategy

    spec = importlib.util.spec_from_file_location("agent_strategy", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["agent_strategy"] = mod
    spec.loader.exec_module(mod)
    classes = [v for v in vars(mod).values()
               if isinstance(v, type) and issubclass(v, Strategy) and v is not Strategy]
    if len(classes) != 1:
        raise ValueError(f"expected one Strategy subclass, found {len(classes)}")
    return classes[0]


def main() -> None:
    with open(f"{JOB}/job.json") as f:
        job = json.load(f)
    nonce = job["nonce"]
    t0 = time.time()
    try:
        with open("/data/panel.pkl", "rb") as f:
            panel = pickle.load(f)
        cls = _load_strategy(f"{JOB}/strategy.py")
        if job["mode"] == "research":
            from research.data.splits import PERIODS
            from research.engine.backtest import run_backtest
            from research.engine.lookahead import check_no_lookahead

            fails = check_no_lookahead(cls, panel, job["lookahead_dates"])
            if fails:
                _emit(nonce, {"ok": False, "stage": "look_ahead", "error": "; ".join(fails)[:2000]})
                return
            results = {}
            for p, (s, e) in PERIODS.items():
                results[p] = run_backtest(cls(), panel, s, e).metrics
            _emit(nonce, {"ok": True, "name": cls.name, "rebalance": cls.rebalance, "params": cls().params(),
                          "results": results, "seconds": round(time.time() - t0, 1)})
        elif job["mode"] == "gate1":
            from research.gates import gate1

            # holdout_start / lookahead_dates are set only by tests on synthetic data; the
            # pipeline never sends them, so real runs use the fixed split.
            kw = {k: job[k] for k in ("holdout_start",) if job.get(k)}
            if job.get("gate_lookahead_dates"):
                kw["lookahead_dates"] = tuple(job["gate_lookahead_dates"])
            r = gate1.run_gate1(cls, panel=panel, n_trials=job["n_trials"], trial_sharpes=job["trial_sharpes"],
                                log=None, **kw)
            _emit(nonce, {"ok": True, "report": asdict(r), "seconds": round(time.time() - t0, 1)})
        else:
            raise ValueError(f"unknown mode {job['mode']!r}")
    except Exception as e:  # report, never crash silently
        tb = traceback.format_exc().splitlines()
        _emit(nonce, {"ok": False, "stage": "run", "error": f"{type(e).__name__}: {e}",
                      "traceback": "\n".join(tb[-25:])})


if __name__ == "__main__":
    main()
