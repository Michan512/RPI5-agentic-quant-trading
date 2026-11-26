"""
Alpaca PAPER trading adapter (alpaca-py). Used on the Raspberry Pi only.

- Paper endpoint is hard-coded; there is no switch to live trading here.
- Keys are passed in by the caller (the Pi's entry point reads them from the
  Pi's own environment). This module never reads .env itself.
- Orders are DAY market orders submitted after the close, so they queue for
  the next open. (Alpaca's opening-auction "OPG" type doesn't support the
  fractional / notional orders this system uses.)

Not exercised on the laptop: the research machine holds no broker keys.
"""

from __future__ import annotations

from live.broker.base import Account, BrokerTimeout, DuplicateOrder, OrderRejected


class AlpacaPaperBroker:
    def __init__(self, api_key: str, secret_key: str):
        from alpaca.trading.client import TradingClient

        if not api_key or not secret_key:
            raise RuntimeError("Alpaca paper keys missing")
        self._client = TradingClient(api_key=api_key, secret_key=secret_key, paper=True)
        base = str(getattr(self._client, "_base_url", ""))
        if "paper" not in base:
            raise RuntimeError(f"refusing to run: client is not on the paper endpoint ({base!r})")

    def account(self) -> Account:
        a = self._call(self._client.get_account)
        return Account(equity=float(a.equity), cash=float(a.cash))

    def positions(self) -> dict[str, float]:
        return {p.symbol: float(p.qty) for p in self._call(self._client.get_all_positions)}

    def submit_order(self, symbol, side, client_order_id, notional=None, qty=None) -> dict:
        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import MarketOrderRequest

        if (notional is None) == (qty is None):
            raise ValueError("give exactly one of notional or qty")
        req = MarketOrderRequest(
            symbol=symbol,
            side=OrderSide.BUY if side == "buy" else OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
            client_order_id=client_order_id,
            **({"notional": round(notional, 2)} if notional is not None else {"qty": qty}),
        )
        o = self._call(self._client.submit_order, req)
        return {"id": str(o.id), "client_order_id": o.client_order_id, "status": str(o.status)}

    def get_order(self, client_order_id) -> dict | None:
        from alpaca.common.exceptions import APIError

        try:
            o = self._call(self._client.get_order_by_client_id, client_order_id)
        except APIError as e:
            if getattr(e, "status_code", None) == 404:
                return None
            raise
        return self._order_dict(o)

    @staticmethod
    def _order_dict(o) -> dict:
        status = str(getattr(o.status, "value", o.status)).lower()
        filled_qty = float(o.filled_qty) if o.filled_qty is not None else 0.0
        price = float(o.filled_avg_price) if o.filled_avg_price is not None else None
        return {"id": str(o.id), "client_order_id": o.client_order_id, "status": status,
                "filled_qty": filled_qty, "filled_price": price}

    @staticmethod
    def _call(fn, *args):
        import requests
        from alpaca.common.exceptions import APIError

        try:
            return fn(*args)
        except (requests.Timeout, requests.ConnectionError) as e:
            raise BrokerTimeout(str(e)) from e
        except APIError as e:
            msg = str(e).lower()
            if "client_order_id" in msg and "unique" in msg:
                raise DuplicateOrder(msg) from e
            if getattr(e, "status_code", None) in (403, 422):
                raise OrderRejected(msg) from e
            raise
