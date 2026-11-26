"""
Promotion gate 1 thresholds. Fixed: set by the owner, never by a strategy or an agent.
Changing one needs a written reason (proposal: "Parts no agent can change").

Confirmed by the owner on 2026-11-26 unless marked otherwise.
"""

# Holdout return (after costs) must beat buy-and-hold of the broad index ...
BEAT_BUY_HOLD = True
# ... and the bank rate (proposal: "the 5% bank rate").
BANK_RATE = 0.05
# Strategies that hold individual stocks must also beat holding all universe
# stocks equally (the fair yardstick under survivorship bias).
STOCK_PICKERS_BEAT_EQUAL_WEIGHT = True

# Deflated Sharpe ratio: probability the true Sharpe beats the best you'd expect
# from luck after N trials. Standard 95% confidence (default, not separately confirmed).
MIN_DEFLATED_SHARPE = 0.95

# Risk limits on the holdout run.
MAX_TURNOVER_ONE_WAY_PER_YEAR = 3.0         # 300% a year
MAX_DRAWDOWN_VS_BUY_HOLD = 0.0              # worst fall no deeper than buy-and-hold's (0 points worse)
MAX_SINGLE_STOCK_WEIGHT_AFTER_DRIFT = 0.30  # 25% cap at rebalance + room for drift (default)

# Robustness: must still beat buy-and-hold with doubled costs, and with the start
# date shifted by these numbers of trading days (~1, 2 and 3 months). (Proposal wording; default sizes.)
COST_MULTIPLIER_STRESS = 2.0
START_SHIFTS_TRADING_DAYS = (21, 42, 63)

# Each exact strategy version gets one attempt at the holdout.
ONE_ATTEMPT_PER_VERSION = True
