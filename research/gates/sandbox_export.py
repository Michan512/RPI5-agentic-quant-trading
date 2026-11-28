"""
Price snapshots for the stage B sandbox. The ONLY place a holdout snapshot is written.

  research snapshot  research/agent/sandbox_data/research/panel.pkl  (no holdout rows)
                     mounted for every agent backtest
  full snapshot      research/gates/sandbox_data/full/panel.pkl      (includes holdout)
                     mounted only for gate 1 runs, whose results the agent never sees

Snapshots are rebuilt when the price files change. They're gitignored.
"""

from __future__ import annotations

import json
import pickle
from pathlib import Path

from research.data.loader import data_version, load_panel

REPO = Path(__file__).resolve().parents[2]
RESEARCH_DIR = REPO / "research" / "agent" / "sandbox_data" / "research"
FULL_DIR = REPO / "research" / "gates" / "sandbox_data" / "full"


def _write(dirpath: Path, include_holdout: bool) -> Path:
    dirpath.mkdir(parents=True, exist_ok=True)
    stamp, pkl = dirpath / "version.json", dirpath / "panel.pkl"
    ver = data_version()
    if pkl.exists() and stamp.exists() and json.loads(stamp.read_text()).get("data_version") == ver:
        return dirpath
    panel = load_panel(include_holdout=include_holdout)      # allowed: this module is research.gates.*
    with pkl.open("wb") as f:
        pickle.dump(panel, f, protocol=4)
    stamp.write_text(json.dumps({"data_version": ver, "include_holdout": include_holdout,
                                 "last_date": str(panel["close"].index[-1].date())}))
    return dirpath


def research_snapshot() -> Path:
    return _write(RESEARCH_DIR, include_holdout=False)


def full_snapshot() -> Path:
    return _write(FULL_DIR, include_holdout=True)
