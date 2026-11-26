"""
In-memory broker simulator for the laptop and the tests. No network, no keys.

- Orders are queued and fill at the next session's open (`open_session`),
  sells first, with the same fee + slippage as the backtest engine.
- A duplicate client_order_id is refused, like Alpaca does.
- A buy that needs more cash than is available is rejected (cash account).
- Failures can be injected to test the engine: timeouts (before or after the
  order is accepted), rejections, and a simulated crash.
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path

from live.broker.base import Account, BrokerTimeout, DuplicateOrder, OrderRejected
from research.engine import settings as S


class SimulatedCrash(BaseException):
    """Stands in for the process dying (BaseException so the engine can't catch it)."""


class FakeBroker:
    def __init__(self, cash: float = S.INITIAL_CASH):
        self.cash = float(cash)
        self.holdings: dict[str, float] = {}
        self.orders: dict[str, dict] = {}         # client_order_id -> order
        self.marks: dict[str, float] = {}          # last known price per symbol
        self.cost_rate = (S.FEE_BPS + S.SLIPPAGE_BPS) / 1e4
        self.failures: dict[int, str] = {}         # submit call number -> failure mode
        self._submits = 0
        self.last_session: str | None = None    # date of the last open simulated
        self._ids = itertools.count(1)

    # ---- failure injection -------------------------------------------------
    def fail_on_submit(self, call_number: int, mode: str) -> None:
        """mode: 'timeout_before' | 'timeout_after' | 'reject' | 'crash' (1-based call number)."""
        self.failures[call_number] = mode

    # ---- Broker interface --------------------------------------------------
    def account(self) -> Account:
        value = sum(q * self.marks.get(s, 0.0) for s, q in self.holdings.items())
        return Account(equity=self.cash + value, cash=self.cash)

    def positions(self) -> dict[str, float]:
        return {s: q for s, q in self.holdings.items() if abs(q) > 1e-12}

    def submit_order(self, symbol, side, client_order_id, notional=None, qty=None) -> dict:
        if (notional is None) == (qty is None):
            raise ValueError("give exactly one of notional or qty")
        self._submits += 1
        mode = self.failures.get(self._submits)
        if mode == "timeout_before":
            raise BrokerTimeout("simulated timeout (order not received)")
        if mode == "reject":
            raise OrderRejected("simulated rejection")
        if client_order_id in self.orders:
            raise DuplicateOrder(client_order_id)
        order = {"id": f"fake-{next(self._ids)}", "client_order_id": client_order_id,
                 "symbol": symbol, "side": side, "notional": notional, "qty": qty,
                 "status": "accepted", "filled_qty": 0.0, "filled_price": None}
        self.orders[client_order_id] = order
        if mode == "timeout_after":
            raise BrokerTimeout("simulated timeout (order was received)")
        if mode == "crash":
            raise SimulatedCrash("simulated crash right after an order was accepted")
        return dict(order)

    def get_order(self, client_order_id) -> dict | None:
        o = self.orders.get(client_order_id)
        return dict(o) if o else None

    # ---- simulation --------------------------------------------------------
    def open_session(self, opens: dict[str, float], session: str | None = None) -> list[dict]:
        """Fill every queued order at these open prices. Returns the orders filled.

        `session` (YYYY-MM-DD) makes this idempotent: a session already opened is skipped.
        """
        if session is not None:
            if self.last_session is not None and session <= self.last_session:
                return []
            self.last_session = session
        pending = [o for o in self.orders.values() if o["status"] == "accepted"]
        filled = []
        for o in sorted(pending, key=lambda o: o["side"] != "sell"):   # sells first
            px = opens.get(o["symbol"])
            if px is None or px != px or px <= 0:
                o["status"] = "expired"                  # no trading in that symbol today
                continue
            held = self.holdings.get(o["symbol"], 0.0)
            if o["side"] == "sell":
                q = min(o["qty"] if o["qty"] is not None else o["notional"] / px, held)
                gross = q * px
                self.cash += gross - gross * self.cost_rate
                self.holdings[o["symbol"]] = held - q
            else:
                gross = o["notional"] if o["notional"] is not None else o["qty"] * px
                need = gross * (1 + self.cost_rate)
                if need > self.cash + 1e-9:
                    o["status"] = "rejected"
                    continue
                q = gross / px
                self.cash -= need
                self.holdings[o["symbol"]] = held + q
            o.update(status="filled", filled_qty=q, filled_price=px)
            filled.append(dict(o))
        self.marks.update({s: p for s, p in opens.items() if p == p})
        return filled

    def mark(self, prices: dict[str, float]) -> None:
        """Update last prices (e.g. at the close) for account valuation."""
        self.marks.update({s: p for s, p in prices.items() if p == p})

    # ---- persistence for the laptop CLI -------------------------------------
    def save(self, path: Path) -> None:
        path.write_text(json.dumps({"cash": self.cash, "holdings": self.holdings,
                                    "orders": self.orders, "marks": self.marks,
                                    "last_session": self.last_session}, indent=2))

    @classmethod
    def load(cls, path: Path) -> "FakeBroker":
        b = cls()
        if path.exists():
            d = json.loads(path.read_text())
            b.cash, b.holdings, b.orders, b.marks = d["cash"], d["holdings"], d["orders"], d["marks"]
            b.last_session = d.get("last_session")
            b._ids = itertools.count(len(b.orders) + 1)
        return b
