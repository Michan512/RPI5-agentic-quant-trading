"""
The risk layer: fixed code between strategy output and the broker.

Two jobs:
  1. guard(): decide whether trading is allowed today at all
     (kill switch, disabled, hard stop, drawdown pause, daily loss halt).
  2. plan_orders(): turn validated target weights into orders, applying the
     turnover cap, cash-only sizing and minimum order size.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from live.risk.limits import RiskLimits
from shared.strategy import validate_weights


@dataclass
class Guard:
    action: str          # ok | kill | disabled | paused | hard_stop | pause | halt_today
    reason: str = ""


def guard(*, kill_switch: bool, disabled: bool, paused: bool, equity: float,
          equity_history: list[float], net_deposits: float, limits: RiskLimits) -> Guard:
    if kill_switch:
        return Guard("kill", "kill switch is on")
    if disabled:
        return Guard("disabled", "system disabled by hard stop; manual reset required")
    if equity - net_deposits <= -limits.hard_stop_loss:
        return Guard("hard_stop", f"loss {equity - net_deposits:,.2f} reached the hard stop "
                                  f"(-{limits.hard_stop_loss:,.0f})")
    if paused:
        return Guard("paused", "trading paused after a drawdown; manual resume required")
    if equity_history:
        peak = max(max(equity_history), equity)
        if peak > 0 and equity / peak - 1 <= -limits.drawdown_pause:
            return Guard("pause", f"drawdown {equity / peak - 1:.1%} reached the {limits.drawdown_pause:.0%} pause level")
        prev = equity_history[-1]
        if prev > 0 and equity / prev - 1 <= -limits.daily_loss_halt:
            return Guard("halt_today", f"daily loss {equity / prev - 1:.1%} reached the {limits.daily_loss_halt:.0%} halt level")
    return Guard("ok")


def current_weights(positions: dict[str, float], prices: pd.Series, equity: float) -> pd.Series:
    if equity <= 0:
        return pd.Series(dtype=float)
    return pd.Series({s: q * prices[s] / equity for s, q in positions.items() if abs(q) > 1e-12}, dtype=float)


def apply_turnover_cap(current: pd.Series, target: pd.Series, cap: float) -> tuple[pd.Series, bool]:
    """Move only part of the way to the target so one-way turnover <= cap."""
    idx = current.index.union(target.index)
    c, t = current.reindex(idx).fillna(0.0), target.reindex(idx).fillna(0.0)
    turnover = (t - c).abs().sum() / 2
    if turnover <= cap + 1e-12:
        return t[t > 0], False
    new = c + (t - c) * (cap / turnover)      # a mix of two valid portfolios is still valid
    return new[new > 1e-12], True


def plan_orders(*, target: pd.Series, positions: dict[str, float], prices: pd.Series,
                equity: float, cash: float, cost_rate: float, limits: RiskLimits,
                run_date: str, tag: str = "portfolio", cap_turnover: bool = True) -> tuple[list[dict], bool]:
    """Return (orders, transition_pending). Orders are sells first, then buys."""
    target = validate_weights(target)
    current = current_weights(positions, prices, equity)
    new, capped = apply_turnover_cap(current, target, limits.turnover_cap) if cap_turnover \
        else (target, False)
    new = validate_weights(new)

    idx = current.index.union(new.index)
    diff = (new.reindex(idx).fillna(0) - current.reindex(idx).fillna(0)) * equity
    stamp = run_date.replace("-", "")
    orders, sell_value = [], 0.0
    for t in sorted(diff.index):
        d = diff[t]
        if d < -limits.min_order_value:
            held = positions.get(t, 0.0)
            qty = held if new.get(t, 0.0) <= 0 else min(held, -d / prices[t])
            orders.append({"client_order_id": f"{stamp}-{tag}-{t}-sell", "ticker": t, "side": "sell", "qty": qty})
            sell_value += qty * prices[t]
    buys = {t: d for t, d in diff.items() if d > limits.min_order_value}
    available = cash + sell_value * (1 - cost_rate) - limits.cash_buffer * equity
    need = sum(buys.values()) * (1 + cost_rate)
    scale = min(1.0, max(available, 0.0) / need) if need > 0 else 1.0
    for t in sorted(buys):
        notional = round(buys[t] * scale, 2)
        if notional >= limits.min_order_value:
            orders.append({"client_order_id": f"{stamp}-{tag}-{t}-buy", "ticker": t, "side": "buy",
                           "notional": notional})
    return orders, capped


def sell_everything(positions: dict[str, float], run_date: str) -> list[dict]:
    stamp = run_date.replace("-", "")
    return [{"client_order_id": f"{stamp}-hardstop-{t}-sell", "ticker": t, "side": "sell", "qty": q}
            for t, q in sorted(positions.items()) if q > 0]
