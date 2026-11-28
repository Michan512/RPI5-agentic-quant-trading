"""
T9: sector momentum with a holding buffer (cost-aware version of T3).

Same signal as T3 (top 3 sectors by 12-1 month momentum, 25% each, rest short
Treasuries, only while US stocks are above their 200-day average, else 7-10y
Treasuries). New: a sector already held is kept while it still ranks in the top 5,
so the portfolio only trades when a holding clearly drops back. Buffer rules like
this are the standard way to cut momentum turnover (e.g. Novy-Marx & Velikov 2016).

A new trial, not a fix of T3: T3 failed on return (validation 6.2% vs 60/40 6.8%)
as well as turnover, and this version is judged by the same pre-set rule.

Stateless: holdings are rebuilt by replaying the rule over past month ends on each
call, so the backtest and the Pi compute the same thing from the same prices.
"""

import pandas as pd

from shared.strategy import PriceView, Strategy
from shared.universe import SECTOR_ETFS, etf


class SectorMomentumBuffer(Strategy):
    name = "sector_momentum_buffer"
    rebalance = "monthly"

    def __init__(self, top_n: int = 3, keep_rank: int = 5, lookback: int = 252, skip: int = 21, sma: int = 200):
        self.top_n, self.keep_rank = top_n, keep_rank
        self.lookback, self.skip, self.sma = lookback, skip, sma

    def params(self) -> dict:
        return {"top_n": self.top_n, "keep_while_rank_within": self.keep_rank, "lookback_days": self.lookback,
                "skip_days": self.skip, "trend_filter_sma_days": self.sma, "weight_each": 0.25}

    def target_weights(self, data: PriceView) -> pd.Series:
        close = data.close[list(SECTOR_ETFS)]
        spy = data.close[etf("broad_index")]
        sma = spy.rolling(self.sma).mean()
        dates = close.index
        # Month-end rows, plus today (the row this call decides for).
        ends = [i for i in range(len(dates) - 1) if dates[i].month != dates[i + 1].month] + [len(dates) - 1]
        held: list = []
        on = False
        for i in ends:
            if i < self.lookback or pd.isna(sma.iloc[i]):
                held, on = [], False
                continue
            on = bool(spy.iloc[i] > sma.iloc[i])
            if not on:
                held = []
                continue
            score = (close.iloc[i - self.skip] / close.iloc[i - self.lookback] - 1).dropna()
            ranked = list(score.sort_values(ascending=False).index)
            keep = [s for s in held if s in ranked[: self.keep_rank]]
            for s in ranked:
                if len(keep) >= self.top_n:
                    break
                if s not in keep:
                    keep.append(s)
            held = keep
        if not on:
            return pd.Series({etf("mid_bond"): 1.0})
        w = pd.Series(0.25, index=held)
        w[etf("short_bond")] = 1.0 - w.sum()
        return w
