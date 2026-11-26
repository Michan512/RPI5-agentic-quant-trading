"""Live-side settings: file locations and the approved-strategy list."""

from __future__ import annotations

import json
from pathlib import Path

LIVE_DIR = Path(__file__).resolve().parent
STATE_DIR = LIVE_DIR / "state"                 # gitignored runtime files
LEDGER_PATH = STATE_DIR / "ledger.db"
FAKE_LEDGER_PATH = STATE_DIR / "ledger_fake.db"
FAKE_BROKER_PATH = STATE_DIR / "fake_broker.json"
KILL_SWITCH = STATE_DIR / "KILL"
HEARTBEAT = STATE_DIR / "heartbeat.json"
APPROVED_PATH = LIVE_DIR / "approved.json"


def load_approved(path: Path = APPROVED_PATH) -> list[dict]:
    """
    Approved strategies and their share of the account, e.g.
      [{"strategy": "trend_sma200", "allocation": 0.5, "half_size": true}, ...]
    Allocations must sum to <= 1. Only strategy names in the registry are allowed.
    """
    entries = json.loads(path.read_text())
    total = sum(e["allocation"] for e in entries)
    if total > 1 + 1e-9:
        raise ValueError(f"allocations sum to {total:.3f} > 1")
    return entries


def strategy_registry() -> dict:
    """Name -> Strategy class. Only these can be approved."""
    from research.strategies import BENCHMARKS

    return dict(BENCHMARKS)
