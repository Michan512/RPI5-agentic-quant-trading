"""
Live risk limits (proposal, "Risk controls"). Changing any value is a risk-limit
change: ask the project owner first.

Per-stock / total weight caps live in shared/limits.py (shared with research).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class RiskLimits:
    # Max share of the portfolio changed per rebalance (one-way: sum|target - current| / 2).
    turnover_cap: float = 0.30
    # No new orders on a day the portfolio fell this much versus the previous run.
    daily_loss_halt: float = 0.03
    # Pause all trading (manual resume) at this fall from the equity peak.
    # Proposal says 15-20%; the stricter end is used. FLAGGED for owner confirmation.
    drawdown_pause: float = 0.15
    # Hard stop: equity + withdrawals - deposits <= -hard_stop_loss -> sell all, disable.
    hard_stop_loss: float = 5_000.0
    # Newly approved strategies trade at this fraction of their allocation.
    half_size_factor: float = 0.5
    # Cash kept back when sizing buys, so overnight gaps don't cause rejected orders.
    cash_buffer: float = 0.005
    # Alpaca's minimum order value; smaller differences are skipped.
    min_order_value: float = 1.0


DEFAULT_LIMITS = RiskLimits()
