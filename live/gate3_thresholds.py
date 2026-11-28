"""
Promotion gate 3 (paper period) thresholds. Fixed: set by the owner, never by a
strategy or an agent. Changing one needs a written reason (proposal: "Parts no
agent can change").

Confirmed by the owner on 2026-11-26.
"""

# Proposal: "First strategy ever to go live: at least 6 months of paper trading."
MIN_MONTHS_FIRST_GO_LIVE = 6
# Proposal: "Replacing an existing live strategy: at least 3 months on paper."
MIN_MONTHS_REPLACE = 3

# "Beats its benchmarks after costs over the period": annualised forward return must
# beat buy-and-hold of the broad index AND the bank rate (owner choice).
BENCHMARK = "buy_hold_index"
BANK_RATE = 0.05

# "Forward results must not differ wildly from what the backtest predicted."
# Forward run = the targets the Pi recorded at the time; prediction = a fresh backtest
# of the same days. Same code and data, so any real gap means a bug or a data problem.
MAX_CUMULATIVE_RETURN_GAP = 0.02      # percentage points of cumulative return over the period
MIN_TARGET_MATCH_SHARE = 0.99         # share of rebalance days where recorded weights = fresh weights
TARGET_MATCH_TOL = 1e-6               # weight difference that still counts as a match
