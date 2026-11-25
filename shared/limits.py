"""
Hard weight limits that every strategy's output must satisfy.

Both the backtest engine (research) and the live risk layer (Pi) check these.
Changing any value here is a risk-limit change: ask the project owner first.
"""

LONG_ONLY = True
MAX_TOTAL_WEIGHT = 1.0      # cash account: weights may sum to at most 100%, rest is cash
MAX_WEIGHT_STOCK = 0.25     # proposal: "25% maximum per stock"

# Interpretation (flagged for the owner): the proposal's 25% cap is "per stock",
# and its own benchmarks hold one broad index ETF at 100% (buy-and-hold, trend).
# So broad ETFs listed in shared/universe.py may be held up to 100%.
MAX_WEIGHT_ETF = 1.0

# Floating-point tolerance used when checking the limits.
TOLERANCE = 1e-9
