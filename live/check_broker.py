"""
Read-only Alpaca paper connection check. Run once on the Pi after setting up its .env:

    python -m live.check_broker

Prints account equity, cash and positions. Never places an order.
"""

from __future__ import annotations

import os

from live import config


def load_pi_env() -> None:
    """Load the Pi's own .env (paper keys, Telegram, heartbeat URL). Pi only."""
    from dotenv import load_dotenv

    load_dotenv(config.LIVE_DIR.parent / ".env")


def pi_broker():
    from live.broker.alpaca_adapter import AlpacaPaperBroker

    load_pi_env()
    return AlpacaPaperBroker(os.environ.get("ALPACA_API_KEY", ""), os.environ.get("ALPACA_SECRET_KEY", ""))


def main() -> None:
    b = pi_broker()
    a = b.account()
    pos = b.positions()
    print(f"[check] connected to Alpaca PAPER: equity ${a.equity:,.2f}, cash ${a.cash:,.2f}")
    print(f"[check] {len(pos)} open position(s)" + (": " + ", ".join(f"{t} {q}" for t, q in pos.items()) if pos else ""))
    if pos:
        print("[check] WARNING: the ledger assumes a flat account at the start. Close these positions "
              "in the Alpaca dashboard before the first run, or reconciliation will report mismatches.")


if __name__ == "__main__":
    main()
