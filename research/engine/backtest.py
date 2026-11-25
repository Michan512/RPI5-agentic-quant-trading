"""
The fixed backtest engine.

Timeline for each trading day d:
  1. At d's open: fill any orders queued from the previous close.
  2. At d's close: mark the portfolio to market.
  3. If d is a rebalance day: give the strategy a PriceView cut at d's close,
     validate its target weights, and queue orders for the next open.

Prices are adjusted for splits and dividends, so returns include dividends.
Costs (fees + slippage) come from research/engine/settings.py and always apply.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from research.engine import settings as S
from research.engine.metrics import summarize
from shared.strategy import PriceView, Strategy, is_rebalance_day, validate_weights


@dataclass
class BacktestResult:
    strategy: str
    start: pd.Timestamp
    end: pd.Timestamp
    equity: pd.Series                      # portfolio value at each close
    weights: pd.DataFrame                  # end-of-day actual weights
    trades: pd.DataFrame                   # one row per fill
    turnover: pd.Series                    # traded notional / portfolio value, per execution day
    costs: float                           # total fees + slippage paid ($)
    metrics: dict = field(default_factory=dict)


def run_backtest(strategy: Strategy, panel: dict[str, pd.DataFrame],
                 start, end) -> BacktestResult:
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    all_dates = panel["close"].index
    dates = all_dates[(all_dates >= start) & (all_dates <= end)]
    if len(dates) < 2:
        raise ValueError("backtest window has fewer than 2 trading days")

    symbols = list(panel["close"].columns)
    opens = panel["open"].loc[dates]
    closes = panel["close"].loc[dates]
    # Last known close, for valuing a holding on a day it has no bar.
    closes_ff = panel["close"].ffill().loc[dates]

    cost_rate = (S.FEE_BPS + S.SLIPPAGE_BPS) / 1e4
    cash = S.INITIAL_CASH
    shares = pd.Series(0.0, index=symbols)
    pending: pd.Series | None = None
    total_costs = 0.0

    equity, weight_rows, turnover, trade_rows = {}, {}, {}, []
    full_index = panel["close"].index

    for i, d in enumerate(dates):
        # 1. Fill queued orders at today's open.
        if pending is not None:
            o = opens.loc[d]
            ref = o.fillna(closes_ff.loc[d])                 # value non-trading names at last close
            value_open = cash + float((shares * ref).sum())
            target_value = pending.reindex(symbols).fillna(0.0) * value_open
            tradable = o.notna() & (o > 0)
            target_sh = shares.copy()
            target_sh[tradable] = target_value[tradable] / o[tradable]
            delta = (target_sh - shares).where(tradable, 0.0)
            if not S.FRACTIONAL_SHARES:
                delta = np.trunc(delta)

            traded = 0.0
            # Sells first, to raise cash.
            for t in delta.index[delta < 0]:
                notional = -delta[t] * o[t]
                cost = notional * cost_rate
                cash += notional - cost
                shares[t] += delta[t]
                total_costs += cost
                traded += notional
                trade_rows.append((d, t, delta[t], o[t], notional, cost))
            # Then buys, scaled down if cash is short (cash only, no margin).
            buys = delta[delta > 0]
            need = float((buys * o[buys.index]).sum()) * (1 + cost_rate)
            scale = min(1.0, cash / need) if need > 0 else 1.0
            for t in buys.index:
                qty = buys[t] * scale
                notional = qty * o[t]
                cost = notional * cost_rate
                cash -= notional + cost
                shares[t] += qty
                total_costs += cost
                traded += notional
                trade_rows.append((d, t, qty, o[t], notional, cost))
            cash = max(cash, 0.0) if abs(cash) < 1e-6 else cash
            turnover[d] = traded / value_open if value_open > 0 else 0.0
            pending = None

        # 2. Mark to market at the close.
        px = closes_ff.loc[d].fillna(0.0)
        holdings = shares * px
        value = cash + float(holdings.sum())
        equity[d] = value
        weight_rows[d] = holdings / value if value > 0 else holdings * 0

        # 3. Ask for new targets at the close (orders fill at the next open).
        if i < len(dates) - 1:
            pos = full_index.get_loc(d)
            if i == 0 or is_rebalance_day(full_index, pos, strategy.rebalance):
                w = strategy.target_weights(PriceView(panel, d))
                pending = validate_weights(w)

    result = BacktestResult(
        strategy=strategy.name, start=dates[0], end=dates[-1],
        equity=pd.Series(equity, name="equity"),
        weights=pd.DataFrame(weight_rows).T,
        trades=pd.DataFrame(trade_rows, columns=["date", "ticker", "qty", "price", "notional", "cost"]),
        turnover=pd.Series(turnover, name="turnover", dtype=float),
        costs=total_costs,
    )
    result.metrics = summarize(result)
    return result
