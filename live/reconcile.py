"""
Ledger vs broker reconciliation (proposal exit check: "ledger matches the broker").

1. For each submitted order whose outcome isn't recorded yet, ask the broker
   and store its status and fill (quantity, price).
2. Rebuild positions from the ledger's fills and compare them with the
   broker's positions. Any difference is logged as an error event and returned.

Run before each daily run: the previous run's orders filled at today's open.
Assumes the account was flat when the ledger started (see deploy/README.md).
"""

from __future__ import annotations

from live.ledger.db import Ledger

QTY_TOL = 1e-6          # shares
REL_TOL = 1e-4


def reconcile(ledger: Ledger, broker, asof: str) -> list[str]:
    for o in ledger.unreconciled_orders():
        info = broker.get_order(o["client_order_id"])
        if info is None:
            ledger.record_fill(o["client_order_id"], "missing_at_broker", None, None)
            continue
        ledger.record_fill(o["client_order_id"], str(info.get("status", "")).lower(),
                           info.get("filled_qty"), info.get("filled_price"))

    problems = []
    for o in ledger.unreconciled_orders():
        if o["broker_status"] == "missing_at_broker":
            problems.append(f"order {o['client_order_id']} is in the ledger but unknown to the broker")
    mine, theirs = ledger.positions_from_fills(), broker.positions()
    for t in sorted(set(mine) | set(theirs)):
        a, b = mine.get(t, 0.0), theirs.get(t, 0.0)
        if abs(a - b) > max(QTY_TOL, REL_TOL * max(abs(a), abs(b))):
            problems.append(f"{t}: ledger says {a:.6f} shares, broker says {b:.6f}")
    for p in problems:
        ledger.log_event(asof, "error", "reconcile_mismatch", p)
    return problems
