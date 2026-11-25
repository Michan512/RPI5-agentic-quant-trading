"""
Evaluate the XGBoost Stage D candidate and record it in the trial log.

1. Walk-forward backtest (yearly retraining) on the research and validation
   periods, after costs, against buy-and-hold over the same windows.
2. Append the result to research/trials/trials.jsonl (every run is a trial).
3. Train one model on all visible data and save it as a new *candidate*
   version in the model registry. It is never used automatically.

Usage (from the repo root):
    python -m research.run_xgb_candidate
"""

from __future__ import annotations

import pandas as pd

from research.data.loader import load_panel
from research.data.splits import LAST_VISIBLE_DATE, PERIODS
from research.engine.backtest import run_backtest
from research.strategies.buy_hold import BuyHold
from research.strategies.xgb_candidate import XGBCandidate, train_model
from research.trials import model_registry
from research.trials.log import log_trial, trial_count

IDEA = ("Legacy XGBoost day-trader rebuilt as a weekly cross-sectional ranker: predict which stocks "
        "beat the median over the next 5 days (from the next open), hold the top 5. "
        "Fixed legacy hyperparameters, no early stopping, yearly walk-forward retraining.")


def evaluate(panel) -> tuple[dict, dict, dict]:
    results, baseline, years = {}, {}, {}
    for period, (start, end) in PERIODS.items():
        strat = XGBCandidate()
        # The first model needs 1 warm-up year + 3 training years, so it starts in 2010.
        eff_start = max(start, pd.Timestamp("2010-01-01"))
        r = run_backtest(strat, panel, eff_start, end)
        b = run_backtest(BuyHold(), panel, eff_start, end)
        m = r.metrics
        m["buy_hold_cagr_same_window"] = b.metrics["cagr"]
        m["buy_hold_max_drawdown_same_window"] = b.metrics["max_drawdown"]
        m["excess_cagr_vs_buy_hold"] = m["cagr"] - b.metrics["cagr"]
        results[period], years[period] = m, dict(strat.train_rows)
        print(f"{period:10s} {m['start']}..{m['end']}  CAGR {m['cagr']:+.2%} vs buy-hold "
              f"{b.metrics['cagr']:+.2%}  MDD {m['max_drawdown']:.1%}  turnover {m['turnover_one_way_per_year']:.0%}/yr")
    return results, baseline, years


def save_candidate_model(panel) -> str:
    strat = XGBCandidate()
    field = lambda n: panel[n]
    model, rows = train_model(field, LAST_VISIBLE_DATE, strat.horizon)
    return model_registry.save_candidate("xgb_candidate", model, {
        "trained_through": str(LAST_VISIBLE_DATE.date()),
        "train_rows": rows,
        "strategy_params": strat.params(),
        "note": "Candidate only. Not evaluated on holdout. Never used automatically.",
    })


if __name__ == "__main__":
    panel = load_panel()
    results, _, train_rows = evaluate(panel)
    tid = log_trial(XGBCandidate(), IDEA, results,
                    notes="Research period measured from 2010-01-01 (first walk-forward model); "
                          "buy-and-hold compared over the same windows.",
                    extra={"train_rows_by_year": train_rows})
    version = save_candidate_model(panel)
    print(f"\nLogged as trial #{tid} (total trials: {trial_count()}).")
    print(f"Saved model candidate xgb_candidate/{version} (status: candidate, not approved).")
