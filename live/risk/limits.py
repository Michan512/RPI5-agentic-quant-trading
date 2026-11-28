"""
Live risk limits (proposal, "Risk controls"). Changing any value is a risk-limit
change: ask the project owner first.

Per-stock / total weight caps live in shared/limits.py (shared with research).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class RiskLimits:
    # Max share of the portfolio changed per rebalance (one-way: sum|target - current| / 2).
    # Moving out of cash is deliberately NOT exempt, so fresh cash is invested over ~2 days
    # (confirmed by the owner 2026-11-26).
    turnover_cap: float = 0.30
    # No new orders on a day the portfolio fell this much versus the previous run.
    daily_loss_halt: float = 0.03
    # Pause all trading (manual resume) at this fall from the equity peak.
    # Proposal says 15-20%; the stricter end, confirmed by the owner 2026-11-26.
    drawdown_pause: float = 0.15
    # Hard stop: equity + withdrawals - deposits <= -hard_stop_loss -> sell all, disable.
    hard_stop_loss: float = 5_000.0
    # Newly approved strategies trade at this fraction of their allocation ...
    half_size_factor: float = 0.5
    # ... for this many calendar days after their live_since date (proposal: "first 4
    # weeks at half position size, then full size if fills and the ledger match").
    half_size_days: int = 28
    # Automatic rollback (proposal, "Automatic replacement"; owner-confirmed 2026-11-26):
    # for this many days after go-live, if the account's cumulative return differs from
    # what the paper books predict by more than drift_limit, switch back to the previous
    # strategy, or pause trading with an alert if there is none.
    drift_window_days: int = 91
    drift_limit: float = 0.03
    # Cash kept back when sizing buys, so overnight gaps don't cause rejected orders.
    cash_buffer: float = 0.005
    # Alpaca's minimum order value; smaller differences are skipped.
    min_order_value: float = 1.0


DEFAULT_LIMITS = RiskLimits()
