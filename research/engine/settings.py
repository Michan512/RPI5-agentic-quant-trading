"""
Fixed backtest settings. Every backtest uses these; strategies cannot override them.

Changing a value here changes every past and future result. Ask the project
owner first, and note the change in the trial log.
"""

INITIAL_CASH = 5_000.0          # proposal's planned account size (USD)

# Costs, charged on every trade's notional value, on each side (buy and sell).
# The proposal gives no numbers; these values were confirmed by the owner on 2026-11-25:
#   - Alpaca charges no commission on US stocks, but SEC/FINRA fees exist -> 1 bp.
#   - Market orders at the open on liquid large caps -> 5 bp slippage.
FEE_BPS = 1.0
SLIPPAGE_BPS = 5.0

# Timing: the strategy sees data up to the close of day T; orders fill at the
# open of the next trading day.
EXECUTION = "next_open"

CASH_ONLY = True                # no margin: buys are scaled down if cash is short
FRACTIONAL_SHARES = True        # Alpaca supports fractional shares

TRADING_DAYS_PER_YEAR = 252


def as_dict() -> dict:
    return {
        "initial_cash": INITIAL_CASH,
        "fee_bps": FEE_BPS,
        "slippage_bps": SLIPPAGE_BPS,
        "execution": EXECUTION,
        "cash_only": CASH_ONLY,
        "fractional_shares": FRACTIONAL_SHARES,
    }
