"""Performance metrics. Strategies are judged on returns after costs, not prediction accuracy."""

from __future__ import annotations

import numpy as np
import pandas as pd

from research.engine import settings as S


def max_drawdown(equity: pd.Series) -> float:
    return float((equity / equity.cummax() - 1).min())


def summarize(result) -> dict:
    eq = result.equity
    years = (eq.index[-1] - eq.index[0]).days / 365.25
    total = eq.iloc[-1] / eq.iloc[0] - 1
    cagr = (1 + total) ** (1 / years) - 1 if years > 0 else float("nan")
    daily = eq.pct_change().dropna()
    vol = daily.std() * np.sqrt(S.TRADING_DAYS_PER_YEAR)
    sharpe = (daily.mean() * S.TRADING_DAYS_PER_YEAR) / vol if vol > 0 else float("nan")
    # One-way turnover: half of (buys + sells) / portfolio value, per year.
    turnover = result.turnover.sum() / 2 / years if years > 0 else float("nan")
    invested = result.weights.sum(axis=1).mean()
    return {
        "start": str(eq.index[0].date()),
        "end": str(eq.index[-1].date()),
        "years": round(years, 2),
        "cagr": float(cagr),
        "total_return": float(total),
        "ann_vol": float(vol),
        "sharpe_rf0": float(sharpe),
        "max_drawdown": max_drawdown(eq),
        "turnover_one_way_per_year": float(turnover),
        "cost_drag_per_year": float(result.costs / eq.mean() / years) if years > 0 else float("nan"),
        "avg_invested": float(invested),
        "n_trades": int(len(result.trades)),
    }
