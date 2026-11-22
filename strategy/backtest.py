"""
Broad diversification backtester.

Each day, buy ALL stocks whose predicted P(UP) exceeds the threshold at
Open and sell at Close. Equal-weight allocation across all picks.
A 0.05% transaction cost is applied per trade (entry + exit).

Supports two modes:
  1. Default: uses the pre-trained model on the standard 80/20 val split.
  2. Stress test: trains a fresh model on data before a custom date range,
     then backtests on that range.

Usage:
  python backtest.py                          # default val split
  python backtest.py --start 2022-01-01 --end 2022-12-31  # stress test
"""

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, log_loss
from xgboost import XGBClassifier

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config
from training.dataset import (
    prepare_backtest_data, prepare_datasets_by_date, FEATURE_COLS,
)

PROB_THRESHOLD = 0.55
TRANSACTION_COST = 0.0005  # 0.05% per trade


def _max_drawdown(equity: pd.Series) -> float:
    """Worst peak-to-trough decline of an equity curve (returned as a negative %)."""
    running_peak = equity.cummax()
    drawdown = equity / running_peak - 1.0
    return float(drawdown.min())


def _compute_metrics(val_df: pd.DataFrame, label: str, verbose: bool = True):
    """Given a DataFrame with prob_up, signal, intraday_return columns, report."""
    daily_records = []
    for date, group in val_df.groupby("date"):
        trades = group[group["signal"] == 1]
        if len(trades) > 0:
            avg_return = trades["intraday_return"].mean() - 2 * TRANSACTION_COST
            daily_records.append({
                "date": date, "strategy_return": avg_return,
                "n_trades": len(trades),
            })
        else:
            daily_records.append({
                "date": date, "strategy_return": 0.0, "n_trades": 0,
            })

    daily = pd.DataFrame(daily_records).set_index("date").sort_index()

    cumulative_return = (1 + daily["strategy_return"]).prod() - 1
    trade_days = daily[daily["n_trades"] > 0]
    total_trades = int(trade_days["n_trades"].sum())
    wins = (trade_days["strategy_return"] > 0).sum()
    win_rate = wins / len(trade_days) if len(trade_days) > 0 else 0.0
    mean_daily = daily["strategy_return"].mean()
    std_daily = daily["strategy_return"].std()
    sharpe = (mean_daily / std_daily) * np.sqrt(252) if std_daily > 0 else 0.0

    # Max drawdown on the compounded equity curve (cash sits flat on no-trade days)
    equity = (1 + daily["strategy_return"]).cumprod()
    max_drawdown = _max_drawdown(equity)

    # Fraction of trading days the model actually took at least one position
    pct_days_traded = len(trade_days) / len(daily) if len(daily) > 0 else 0.0

    # SPY benchmark
    spy_path = config.DATA_DIR / "SPY.csv"
    spy_full = pd.read_csv(spy_path, index_col=0, parse_dates=True)
    start_date, end_date = daily.index[0], daily.index[-1]
    spy_val = spy_full.loc[start_date:end_date]
    spy_cumulative = (
        (spy_val["Close"].iloc[-1] / spy_val["Close"].iloc[0]) - 1
        if not spy_val.empty else float("nan")
    )

    if verbose:
        print("=" * 55)
        print(f"  BACKTEST RESULTS  ({label})")
        print("=" * 55)
        print(f"  Period               : {start_date.date()} -> {end_date.date()}")
        print(f"  Trading days         : {len(daily)}")
        print(f"  Days with trades     : {len(trade_days)}")
        print(f"  % days traded        : {pct_days_traded:.2%}")
        print(f"  Total trades (picks) : {total_trades}")
        print(f"  Win rate (by day)    : {win_rate:.2%}")
        print(f"  Strategy cumulative  : {cumulative_return:.2%}")
        print(f"  SPY buy-and-hold     : {spy_cumulative:.2%}")
        print(f"  Sharpe ratio (ann.)  : {sharpe:.2f}")
        print(f"  Max drawdown         : {max_drawdown:.2%}")
        print("=" * 55)

    return {
        "cumulative_return": cumulative_return,
        "spy_return": spy_cumulative,
        "win_rate": win_rate,
        "sharpe": sharpe,
        "max_drawdown": max_drawdown,
        "total_trades": total_trades,
        "pct_days_traded": pct_days_traded,
        "n_trading_days": len(daily),
    }


def run_backtest(tickers: list[str] | None = None):
    """Default backtest using the pre-trained model and 80/20 val split."""
    model_path = config.MODELS_DIR / "trading_model_xgb.json"
    model = XGBClassifier()
    model.load_model(str(model_path))
    print(f"[backtest] Loaded model from {model_path}")

    X_val, y_val, val_df, scaler = prepare_backtest_data(tickers)
    probs = model.predict_proba(X_val)[:, 1]

    val_df = val_df.reset_index(drop=True)
    val_df["prob_up"] = probs
    val_df["intraday_return"] = (val_df["Close"] - val_df["Open"]) / val_df["Open"]
    val_df["signal"] = (val_df["prob_up"] > PROB_THRESHOLD).astype(int)

    print(f"[backtest] Validation rows: {len(val_df)}  "
          f"({val_df['ticker'].nunique()} tickers)")
    print(f"[backtest] Strategy: Broad (prob > {PROB_THRESHOLD})")
    print(f"[backtest] Prob range: {probs.min():.4f} - {probs.max():.4f}")
    print(f"[backtest] Transaction cost: {TRANSACTION_COST*100:.2f}% per trade\n")

    return _compute_metrics(val_df, f"Broad, prob > {PROB_THRESHOLD}")


def run_threshold_sensitivity(tickers: list[str] | None = None,
                              thresholds: list[float] | None = None):
    """Evaluate the default backtest across several buy thresholds and compare.

    The model is loaded and probabilities computed exactly once; only the
    signal cutoff changes between runs, so differences are purely attributable
    to the threshold.
    """
    thresholds = thresholds or [0.53, 0.54, 0.55]

    model_path = config.MODELS_DIR / "trading_model_xgb.json"
    model = XGBClassifier()
    model.load_model(str(model_path))
    print(f"[sensitivity] Loaded model from {model_path}")

    X_val, y_val, val_df, scaler = prepare_backtest_data(tickers)
    probs = model.predict_proba(X_val)[:, 1]

    val_df = val_df.reset_index(drop=True)
    val_df["prob_up"] = probs
    val_df["intraday_return"] = (val_df["Close"] - val_df["Open"]) / val_df["Open"]

    print(f"[sensitivity] Validation rows: {len(val_df)}  "
          f"({val_df['ticker'].nunique()} tickers)")
    print(f"[sensitivity] Prob range: {probs.min():.4f} - {probs.max():.4f}")
    print(f"[sensitivity] Transaction cost: {TRANSACTION_COST*100:.2f}% per trade")
    print(f"[sensitivity] Thresholds: {[f'{t:.0%}' for t in thresholds]}\n")

    results = {}
    for thr in thresholds:
        val_df["signal"] = (val_df["prob_up"] > thr).astype(int)
        results[thr] = _compute_metrics(val_df, f"prob > {thr}", verbose=False)

    # ── Comparison table ────────────────────────────────────────────────
    spy_ret = next(iter(results.values()))["spy_return"]
    header = f"  THRESHOLD SENSITIVITY  (SPY buy-and-hold: {spy_ret:.2%})"
    print("=" * 72)
    print(header)
    print("=" * 72)
    row_fmt = "  {:<22s}" + "".join(f"{{:>14s}}" for _ in thresholds)
    print(row_fmt.format("Buy threshold", *[f"{t:.0%}" for t in thresholds]))
    print("-" * 72)

    def line(metric_label, key, fmt):
        print(row_fmt.format(
            metric_label, *[fmt(results[t][key]) for t in thresholds]
        ))

    line("Cumulative return", "cumulative_return", lambda v: f"{v:.2%}")
    line("Sharpe ratio (ann.)", "sharpe", lambda v: f"{v:.2f}")
    line("Max drawdown", "max_drawdown", lambda v: f"{v:.2%}")
    line("Total trades", "total_trades", lambda v: f"{v:,d}")
    line("% days traded", "pct_days_traded", lambda v: f"{v:.2%}")
    print("=" * 72)

    return results


def run_stress_test(start: str, end: str, tickers: list[str] | None = None):
    """Train a fresh model on data before *start*, then backtest on [start, end]."""
    print(f"[stress] Training on data before {start}, testing {start} -> {end}")

    X_train, y_train, X_test, y_test, test_df, scaler = prepare_datasets_by_date(
        train_end=start, test_start=start, test_end=end, tickers=tickers,
    )

    model = XGBClassifier(
        n_estimators=300,
        max_depth=5,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        min_child_weight=5,
        reg_alpha=0.1,
        reg_lambda=1.0,
        eval_metric="logloss",
        early_stopping_rounds=20,
        verbosity=1,
    )

    t0 = time.perf_counter()
    model.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=20)
    duration = time.perf_counter() - t0

    y_pred = model.predict(X_test)
    y_prob = model.predict_proba(X_test)[:, 1]
    val_acc = accuracy_score(y_test, y_pred)
    val_ll = log_loss(y_test, y_prob)

    print(f"\n[stress] Best iteration : {model.best_iteration}")
    print(f"[stress] Val Accuracy   : {val_acc:.4f}")
    print(f"[stress] Val Log-Loss   : {val_ll:.4f}")
    print(f"[stress] Training Time  : {duration:.2f}s")

    # Feature importances (top 5)
    importances = model.feature_importances_
    indices = np.argsort(importances)[::-1]
    print(f"\n[stress] Top 5 Feature Importances:")
    for rank, idx in enumerate(indices[:5], 1):
        print(f"  {rank}. {FEATURE_COLS[idx]:<20s}  {importances[idx]:.4f}")

    test_df = test_df.reset_index(drop=True)
    test_df["prob_up"] = y_prob
    test_df["intraday_return"] = (test_df["Close"] - test_df["Open"]) / test_df["Open"]
    test_df["signal"] = (test_df["prob_up"] > PROB_THRESHOLD).astype(int)

    print(f"\n[stress] Test rows: {len(test_df)}  "
          f"({test_df['ticker'].nunique()} tickers)")
    print(f"[stress] Prob range: {y_prob.min():.4f} - {y_prob.max():.4f}")
    print(f"[stress] Transaction cost: {TRANSACTION_COST*100:.2f}% per trade\n")

    return _compute_metrics(test_df, f"Stress {start} -> {end}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=str, default=None,
                        help="Stress test start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, default=None,
                        help="Stress test end date (YYYY-MM-DD)")
    parser.add_argument("--sensitivity", action="store_true",
                        help="Run threshold sensitivity analysis (53/54/55%%)")
    args = parser.parse_args()

    if args.sensitivity:
        run_threshold_sensitivity()
    elif args.start and args.end:
        run_stress_test(args.start, args.end)
    else:
        run_backtest()
