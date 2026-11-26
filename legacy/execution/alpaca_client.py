"""
Alpaca Paper Trading execution engine.

Provides two main actions:
  - execute_morning_buys():  fetch signals, buy qualifying stocks
  - execute_afternoon_sells(): liquidate all open positions
"""

import sys
from pathlib import Path

from dotenv import load_dotenv

# Load .env before importing config so env vars are available
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce


# ── Client setup ──────────────────────────────────────────────────────────

def get_client() -> TradingClient:
    """Return an authenticated Alpaca paper-trading client."""
    if not config.ALPACA_API_KEY or not config.ALPACA_SECRET_KEY:
        raise RuntimeError(
            "Alpaca credentials not set. "
            "Create a .env file with ALPACA_API_KEY and ALPACA_SECRET_KEY."
        )
    return TradingClient(
        api_key=config.ALPACA_API_KEY,
        secret_key=config.ALPACA_SECRET_KEY,
        paper=True,
    )


def get_account_cash() -> float:
    """Return available cash in the paper account."""
    client = get_client()
    account = client.get_account()
    return float(account.cash)


def get_positions() -> list:
    """Return all open positions."""
    client = get_client()
    return client.get_all_positions()


# ── Morning: buy qualifying stocks ───────────────────────────────────────

def execute_morning_buys(signals_df=None):
    """
    Fetch today's signals (or accept a pre-computed DataFrame),
    filter to stocks above the buy threshold, and submit equal-weight
    market buy orders using available paper cash.

    Parameters
    ----------
    signals_df : pd.DataFrame, optional
        Must have columns ['Ticker', 'P(UP)']. If None, signals are
        fetched live via live_predict.get_signals().
    """
    # Import here to avoid circular imports at module level
    from live_predict import get_signals, print_report

    if signals_df is None:
        signals_df = get_signals()
        print_report(signals_df)

    buys = signals_df[signals_df["P(UP)"] > config.BUY_THRESHOLD]

    if buys.empty:
        print("\n[alpaca] No stocks above threshold. No orders placed.")
        return []

    # Calculate equal-dollar allocation
    cash = get_account_cash()
    deploy = cash * config.CASH_ALLOCATION
    per_stock = deploy / len(buys)

    print(f"\n[alpaca] Account cash  : ${cash:,.2f}")
    print(f"[alpaca] Deploying     : ${deploy:,.2f} "
          f"({config.CASH_ALLOCATION:.0%} of cash)")
    print(f"[alpaca] Per stock     : ${per_stock:,.2f} "
          f"across {len(buys)} stocks\n")

    client = get_client()
    orders = []
    for _, row in buys.iterrows():
        ticker = row["Ticker"]
        try:
            request = MarketOrderRequest(
                symbol=ticker,
                notional=round(per_stock, 2),  # dollar amount (fractional shares)
                side=OrderSide.BUY,
                time_in_force=TimeInForce.DAY,
            )
            order = client.submit_order(request)
            print(f"  [BUY]  {ticker:<6}  ${per_stock:>10,.2f}  "
                  f"P(UP)={row['P(UP)']:.2%}  status={order.status}")
            orders.append(order)
        except Exception as e:
            print(f"  [ERR]  {ticker:<6}  {e}")

    print(f"\n[alpaca] {len(orders)} buy order(s) submitted.")
    return orders


# ── Afternoon: sell all positions ─────────────────────────────────────────

def execute_afternoon_sells():
    """Liquidate every open stock position with market sell orders."""
    client = get_client()
    positions = get_positions()

    if not positions:
        print("[alpaca] No open positions to sell.")
        return []

    print(f"[alpaca] Liquidating {len(positions)} position(s):\n")

    orders = []
    for pos in positions:
        ticker = pos.symbol
        qty = pos.qty
        unrealized = float(pos.unrealized_pl)
        try:
            request = MarketOrderRequest(
                symbol=ticker,
                qty=qty,
                side=OrderSide.SELL,
                time_in_force=TimeInForce.DAY,
            )
            order = client.submit_order(request)
            pl_str = f"+${unrealized:,.2f}" if unrealized >= 0 else f"-${abs(unrealized):,.2f}"
            print(f"  [SELL] {ticker:<6}  qty={qty:<10}  "
                  f"P&L={pl_str}  status={order.status}")
            orders.append(order)
        except Exception as e:
            print(f"  [ERR]  {ticker:<6}  {e}")

    print(f"\n[alpaca] {len(orders)} sell order(s) submitted.")
    return orders


if __name__ == "__main__":
    print("[alpaca] Checking account status ...")
    try:
        cash = get_account_cash()
        positions = get_positions()
        print(f"[alpaca] Cash available: ${cash:,.2f}")
        print(f"[alpaca] Open positions: {len(positions)}")
        for p in positions:
            print(f"  {p.symbol:<6}  qty={p.qty}  P&L=${float(p.unrealized_pl):,.2f}")
    except RuntimeError as e:
        print(f"[alpaca] {e}")
