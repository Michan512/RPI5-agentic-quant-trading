"""
Automatic promotion and replacement on the Pi (proposal, "Go-live" and "Automatic
replacement": "A new strategy that passes all gates, including beating the live one
on paper, replaces it... You're notified of every promotion, replacement and rollback").

Once a week (the last trading day of the week, after a completed daily run):
  1. Candidates = strategies that passed gates 1 and 2 (the agent registry filled by
     research/agent/pipeline.py, plus owner-listed live/eligible.json), that have a
     paper record on this Pi (shadow books), excluding what's trading now.
     Benchmarks are never promoted.
  2. Each is judged by gate 3 (live/gate3.py). Replacing a strategy that was itself
     promoted needs 6 weeks and beating it; anything else counts as a first go-live
     (3 months, beat buy-and-hold and 5%). Periods in live/gate3_thresholds.py.
  3. The best passing candidate is written to the ledger as the promotion entry
        {"strategy", "allocation": 1.0, "live_since": next trading day, "previous": current}
     and the engine trades it instead of approved.json's list. live/golive.py then does
     the rest unchanged: half size for 4 weeks, then the 3-month drift check with
     automatic rollback to "previous".

Guards: one promotion at a time; none while paused, disabled, or while the current
strategy is in its 3-month drift window; a strategy once rolled back is never
auto-promoted again; a new approved.json from git (the owner)
always wins and clears the promotion. Every promotion logs a critical event (alert).
The Pi never edits approved.json: the one-way channel stays intact.

This trades the account the Pi is connected to, which is the Alpaca PAPER account.
Moving real money (deposit, AUD->USD, live keys) stays the owner's manual step.
"""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta

import pandas as pd

from live import config
from live.engine.calendar import is_trading_day
from live.golive import ReadOnlyLedger, effective_entries
from live.ledger.db import Ledger
from live.risk.limits import RiskLimits

KEY = "promotion"


def approved_hash(approved: list[dict]) -> str:
    return hashlib.sha256(json.dumps(approved, sort_keys=True).encode()).hexdigest()[:12]


def eligible_names() -> set[str]:
    from research.strategies.agent import agent_strategies

    names = set(agent_strategies())
    if config.ELIGIBLE_PATH.exists():
        names |= set(json.loads(config.ELIGIBLE_PATH.read_text()))
    return names


def effective_approved(approved: list[dict], ledger: Ledger, ds: str | None = None) -> list[dict]:
    """approved.json, overlaid by an active promotion. A changed approved.json clears it."""
    p = ledger.get_value(KEY)
    if not p:
        return approved
    if p.get("approved_hash") != approved_hash(approved):
        ledger.set_value(KEY, None)
        if ds:
            ledger.log_event(ds, "warning", "promotion_cleared",
                             f"approved.json changed (new release); promotion of {p['strategy']} cleared, "
                             f"approved.json applies")
        return approved
    return [{"strategy": p["strategy"], "allocation": p["allocation"], "live_since": p["live_since"],
             "previous": p["previous"]}]


def _next_trading_day(d: pd.Timestamp) -> pd.Timestamp:
    n = d + timedelta(days=1)
    while not is_trading_day(n):
        n += timedelta(days=1)
    return n


def consider(approved: list[dict], ledger: Ledger, panel: dict, d: pd.Timestamp, ds: str, limits: RiskLimits,
             registry: dict, eligible: set[str], shadows: list[str]) -> dict | None:
    """Run the weekly promotion check. Returns the new promotion entry, or None."""
    from live.gate3 import evaluate

    eff = effective_approved(approved, ledger, ds)
    if ledger.get_flag("paused") or ledger.get_flag("disabled"):
        return None
    if len(eff) != 1:
        ledger.log_event(ds, "info", "promotion_skipped", "more than one strategy approved; promotion needs one")
        return None
    cur_entry = eff[0]
    trading = effective_entries(eff, ReadOnlyLedger(ledger), d, ds, limits)[0]
    current = trading.strategy
    since = cur_entry.get("live_since")
    if since and not trading.rolled_back_from and d <= pd.Timestamp(since) + timedelta(days=limits.drift_window_days):
        return None                                   # let the current one finish its drift window first
    # A strategy that was rolled back for drifting from its paper record is never promoted
    # again automatically (found in testing: the same weekly check re-promoted it the day
    # it was rolled back, undoing the rollback). A new version has to earn its own record.
    rolled_back = {k.split(":")[1] for k in ledger.true_flags("rolled_back:")}
    candidates = [n for n in shadows if n in eligible and n != current and n not in rolled_back]
    best = None
    for name in candidates:
        replacing = current if current in eligible else None   # a benchmark isn't a "live strategy"
        r = evaluate(name, ledger, panel, registry, replacing=replacing, end=d)
        if r.verdict == "pass" and (best is None or r.metrics["forward_cagr"] > best[1].metrics["forward_cagr"]):
            best = (name, r)
    if best is None:
        return None
    name, r = best
    entry = {"strategy": name, "allocation": 1.0, "live_since": str(_next_trading_day(d).date()),
             "previous": current, "promoted_on": ds, "approved_hash": approved_hash(approved),
             "gate3": {"months": r.months, "forward_cagr": r.metrics["forward_cagr"],
                       "buy_hold_cagr": r.metrics["buy_hold_cagr"]}}
    ledger.set_value(KEY, entry)
    ledger.log_event(ds, "critical", "promotion",
                     f"{name} passed gate 3 ({r.months} months on paper, {r.metrics['forward_cagr']:+.1%}/yr vs "
                     f"buy-and-hold {r.metrics['buy_hold_cagr']:+.1%}) and replaces {current} from "
                     f"{entry['live_since']}: half size for 4 weeks, rollback to {current} on drift. This is the "
                     f"PAPER account; real money stays your manual step. Undo: python -m live.kill --clear-promotion")
    return entry
