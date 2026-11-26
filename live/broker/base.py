"""
The broker interface the live engine talks to. Implementations:
  - live/broker/fake.py           in-memory simulator (laptop, tests)
  - live/broker/alpaca_adapter.py Alpaca paper trading (Pi only)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class BrokerTimeout(Exception):
    """The broker didn't answer in time. The order may or may not have been accepted."""


class DuplicateOrder(Exception):
    """An order with this client_order_id already exists at the broker."""


class OrderRejected(Exception):
    """The broker refused the order (e.g. not enough cash)."""


@dataclass
class Account:
    equity: float
    cash: float


class Broker(Protocol):
    def account(self) -> Account: ...

    def positions(self) -> dict[str, float]:
        """Symbol -> quantity held (fractional allowed)."""

    def submit_order(self, symbol: str, side: str, client_order_id: str,
                     notional: float | None = None, qty: float | None = None) -> dict:
        """Queue a market order for the next open. Exactly one of notional/qty."""

    def get_order(self, client_order_id: str) -> dict | None:
        """Look an order up by our own id; None if the broker never received it."""
