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
ELIGIBLE_PATH = LIVE_DIR / "eligible.json"   # owner-listed strategies that passed gates 1+2 (besides agent ones)
SHADOW_PATH = LIVE_DIR / "shadow.json"       # paper-comparison books (gate 3); never traded


def load_approved(path: Path = APPROVED_PATH) -> list[dict]:
    """
    Approved strategies and their share of the account, e.g.
      [{"strategy": "trend_sma200", "allocation": 0.5, "half_size": true}, ...]
    Going live: add "live_since": "YYYY-MM-DD" (half size for 4 weeks, then drift-checked
    for 3 months) and "previous": "<name>" (what a drift rollback switches back to).
    See live/golive.py.
    Allocations must sum to <= 1. Only strategy names in the registry are allowed.
    """
    entries = json.loads(path.read_text())
    total = sum(e["allocation"] for e in entries)
    if total > 1 + 1e-9:
        raise ValueError(f"allocations sum to {total:.3f} > 1")
    return entries


def strategy_registry() -> dict:
    """Name -> Strategy class. Only these can trade: the benchmarks, and agent strategies that
    passed gates 1 and 2 (they still need gate 3 on paper before live/promotion.py promotes them)."""
    from research.strategies import BENCHMARKS
    from research.strategies.agent import agent_strategies

    return {**BENCHMARKS, **agent_strategies()}


def load_shadows(path: Path = SHADOW_PATH) -> list[str]:
    """Strategies tracked as shadow books: computed and recorded every day, never traded."""
    return json.loads(path.read_text()) if path.exists() else []


def shadow_registry() -> dict:
    """Name -> Strategy class for shadow books: benchmarks plus research candidates.
    Being shadowed doesn't approve anything for trading (that's strategy_registry + approved.json)."""
    from research.strategies import BENCHMARKS, ETF_ROUND1, ETF_ROUND2
    from research.strategies.agent import agent_strategies

    return {**BENCHMARKS, **ETF_ROUND1, **ETF_ROUND2, **agent_strategies()}
