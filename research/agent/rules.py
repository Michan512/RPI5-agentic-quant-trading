"""
The screen an agent idea must pass on research AND validation before it is submitted
to the promotion gates. Fixed: the agent can't change it.

It mirrors gate 1's own bar, so a holdout attempt is only spent on ideas that already
cleared it on the data the agent was allowed to see:
  - CAGR above buy-and-hold of the broad index, and above the 5% bank rate
  - worst fall no deeper than buy-and-hold's
  - turnover within gate 1's limit (300%/yr one-way)
  - strategies that hold single stocks must also beat an equal-weight hold of all of them
"""

from __future__ import annotations

from research.data.splits import PERIODS
from research.gates import thresholds as T


def screen(results: dict, bench: dict, holds_stocks: bool) -> tuple[bool, list[str]]:
    reasons = []
    for p in PERIODS:
        m, bh = results[p], bench[p]["buy_hold_index"]
        if m["cagr"] <= bh["cagr"]:
            reasons.append(f"{p}: CAGR {m['cagr']:.1%} not above buy-and-hold {bh['cagr']:.1%}")
        if m["cagr"] <= T.BANK_RATE:
            reasons.append(f"{p}: CAGR {m['cagr']:.1%} not above the {T.BANK_RATE:.0%} bank rate")
        if m["max_drawdown"] < bh["max_drawdown"] - T.MAX_DRAWDOWN_VS_BUY_HOLD:
            reasons.append(f"{p}: worst fall {m['max_drawdown']:.1%} deeper than buy-and-hold's "
                           f"{bh['max_drawdown']:.1%}")
        if m["turnover_one_way_per_year"] > T.MAX_TURNOVER_ONE_WAY_PER_YEAR:
            reasons.append(f"{p}: turnover {m['turnover_one_way_per_year']:.0%}/yr above "
                           f"{T.MAX_TURNOVER_ONE_WAY_PER_YEAR:.0%}")
        if holds_stocks and m["cagr"] <= bench[p]["equal_weight_universe"]["cagr"]:
            reasons.append(f"{p}: holds stocks but CAGR {m['cagr']:.1%} not above equal-weight "
                           f"{bench[p]['equal_weight_universe']['cagr']:.1%}")
    return not reasons, reasons
