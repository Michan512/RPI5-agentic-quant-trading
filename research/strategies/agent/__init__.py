"""
Agent-written strategies that passed gates 1 and 2 (filed by research/agent/pipeline.py).

They are added to live/shadow.json for their gate 3 paper period. registry.json lists
the module names; nothing here is approved for live trading by being listed.
"""

import importlib
import json
from pathlib import Path

REGISTRY = Path(__file__).resolve().parent / "registry.json"


def agent_strategies() -> dict:
    from shared.strategy import Strategy

    out = {}
    names = json.loads(REGISTRY.read_text()) if REGISTRY.exists() else []
    for name in names:
        mod = importlib.import_module(f"research.strategies.agent.{name}")
        for v in vars(mod).values():
            if isinstance(v, type) and issubclass(v, Strategy) and v is not Strategy:
                out[v.name] = v
    return out
