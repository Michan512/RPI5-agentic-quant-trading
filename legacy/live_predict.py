"""
Real-time signal generator for the next trading session.

Fetches the latest market data via yfinance, engineers the same 34 causal
features used in training, loads the XGBoost model, and prints ranked
UP-probability predictions for each of the 20 tracked stocks.

Usage:
    python live_predict.py
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config
from training.dataset import (
    compute_rsi, compute_macd, compute_bollinger,
    compute_atr, compute_stochastic, compute_obv,
    FEATURE_COLS, _build_combined,
)

# How many calendar days of history to fetch (need ~60 trading days for SMA_50)
LOOKBACK_DAYS = 120


def _fetch_recent(ticker: str, days: int = LOOKBACK_DAYS) -> pd.DataFrame:
    """Download recent daily OHLCV for a single ticker."""
    end = datetime.today() + timedelta(days=1)
    start = end - timedelta(days=days)
    df = yf.download(ticker, start=start.strftime("%Y-%m-%d"),
                     end=end.strftime("%Y-%m-%d"), progress=False)
    if df.empty:
        return df
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df[["Open", "High", "Low", "Close", "Volume"]]


def _engineer_live(ticker_df: pd.DataFrame,
                   spy_df: pd.DataFrame,
                   vix_df: pd.DataFrame) -> pd.Series | None:
    """
    Engineer the 34 causal features for the LAST row of ticker_df.
    Returns a single-row Series aligned with FEATURE_COLS, or None on failure.
    """
    df = ticker_df.copy()

    # Raw indicators (computed on full history including latest close)
    raw_rsi = compute_rsi(df["Close"])
    raw_macd, raw_macd_sig, raw_macd_hist = compute_macd(df["Close"])
    raw_bb_upper, raw_bb_lower, raw_bb_pctb = compute_bollinger(df["Close"])
    raw_atr = compute_atr(df)
    raw_stoch_k, raw_stoch_d = compute_stochastic(df)
    raw_obv = compute_obv(df)
    raw_sma10 = df["Close"].rolling(window=config.SMA_SHORT).mean()
    raw_sma50 = df["Close"].rolling(window=config.SMA_LONG).mean()
    raw_daily_ret = df["Close"].pct_change()
    raw_vol_sma = df["Volume"] / df["Volume"].rolling(window=20).mean()
    raw_roc10 = df["Close"].pct_change(periods=10)

    # SPY return series aligned to ticker dates
    spy_ret = spy_df["Close"].pct_change()

    # VIX raw series
    vix_open_s = vix_df["Open"]
    vix_close_s = vix_df["Close"]

    # Build a working DataFrame for the shift logic
    w = pd.DataFrame(index=df.index)

    # All shifted by 1 (yesterday's values)
    w["prev_close"]    = df["Close"].shift(1)
    w["prev_open"]     = df["Open"].shift(1)
    w["prev_high"]     = df["High"].shift(1)
    w["prev_low"]      = df["Low"].shift(1)
    w["prev_volume"]   = df["Volume"].shift(1)
    w["SMA_10"]        = raw_sma10.shift(1)
    w["SMA_50"]        = raw_sma50.shift(1)
    w["RSI"]           = raw_rsi.shift(1)
    w["daily_return"]  = raw_daily_ret.shift(1)
    w["MACD"]          = raw_macd.shift(1)
    w["MACD_signal"]   = raw_macd_sig.shift(1)
    w["MACD_hist"]     = raw_macd_hist.shift(1)
    w["BB_upper"]      = raw_bb_upper.shift(1)
    w["BB_lower"]      = raw_bb_lower.shift(1)
    w["BB_pctB"]       = raw_bb_pctb.shift(1)
    w["ATR"]           = raw_atr.shift(1)
    w["Stoch_K"]       = raw_stoch_k.shift(1)
    w["Stoch_D"]       = raw_stoch_d.shift(1)
    w["OBV"]           = raw_obv.shift(1)
    w["vol_sma_ratio"] = raw_vol_sma.shift(1)
    w["ROC_10"]        = raw_roc10.shift(1)

    # SPY return lag 1
    w["spy_return_lag_1"] = spy_ret.reindex(df.index).shift(1)

    # VIX features
    w["vix_open"]         = vix_open_s.reindex(df.index)        # today's VIX open
    w["vix_lag_1"]        = vix_close_s.reindex(df.index).shift(1)
    w["vix_change_lag_1"] = (vix_close_s - vix_open_s).reindex(df.index).shift(1)

    # Lagged features
    for lag in range(1, 4):
        w[f"daily_return_lag_{lag}"] = raw_daily_ret.shift(1 + lag)
        w[f"RSI_lag_{lag}"]         = raw_rsi.shift(1 + lag)
        w[f"MACD_lag_{lag}"]        = raw_macd.shift(1 + lag)

    # Take the last row (= features for the upcoming session)
    last = w.iloc[-1]
    if last.isna().any():
        missing = last[last.isna()].index.tolist()
        print(f"  WARNING: NaN in features for latest row: {missing}")
        return None

    return last[FEATURE_COLS]


def get_signals(threshold: float = config.BUY_THRESHOLD) -> pd.DataFrame:
    """
    Fetch live data, engineer features, and return a DataFrame with columns:
        Ticker, P(UP)
    sorted by probability descending. Used by both the CLI report and the
    Alpaca execution engine.
    """
    print("[live] Fetching recent market data ...")

    spy_df = _fetch_recent("SPY")
    vix_df = _fetch_recent("^VIX")

    if spy_df.empty or vix_df.empty:
        print("[live] ERROR: Could not fetch SPY or VIX data.")
        return pd.DataFrame(columns=["Ticker", "P(UP)"])

    # Fetch all tickers
    ticker_data = {}
    for t in config.DEFAULT_TICKERS:
        df = _fetch_recent(t)
        if not df.empty:
            ticker_data[t] = df
        else:
            print(f"  WARNING: No data for {t}")

    # Load model
    model_path = config.MODELS_DIR / "trading_model_xgb.json"
    model = XGBClassifier()
    model.load_model(str(model_path))

    # Fit scaler on historical training data
    combined = _build_combined()
    split_idx = int(len(combined) * config.TRAIN_SPLIT)
    train_df = combined.iloc[:split_idx]
    scaler = StandardScaler()
    scaler.fit(train_df[FEATURE_COLS].values)

    # Engineer features and predict for each ticker
    results = []
    for ticker, tdf in ticker_data.items():
        row = _engineer_live(tdf, spy_df, vix_df)
        if row is not None:
            X = scaler.transform(row.values.reshape(1, -1))
            prob = model.predict_proba(X)[0, 1]
            results.append({"Ticker": ticker, "P(UP)": prob})

    if not results:
        return pd.DataFrame(columns=["Ticker", "P(UP)"])

    results_df = pd.DataFrame(results).sort_values("P(UP)", ascending=False)
    results_df.reset_index(drop=True, inplace=True)

    # Print context
    latest_date = spy_df.index[-1]
    vix_open_today = vix_df["Open"].iloc[-1]
    vix_close_prev = vix_df["Close"].iloc[-2] if len(vix_df) >= 2 else float("nan")
    spy_ret_prev = (spy_df["Close"].iloc[-1] / spy_df["Close"].iloc[-2] - 1
                    if len(spy_df) >= 2 else float("nan"))
    print(f"[live] Data as-of       : {latest_date.date()}")
    print(f"[live] VIX open (today) : {vix_open_today:.2f}")
    print(f"[live] VIX close (prev) : {vix_close_prev:.2f}")
    print(f"[live] SPY return (prev): {spy_ret_prev:+.2%}")

    return results_df


def print_report(results_df: pd.DataFrame,
                 threshold: float = config.BUY_THRESHOLD):
    """Print the ranked signal table and actionable trades."""
    if results_df.empty:
        print("[live] ERROR: No valid predictions could be generated.")
        return

    display = results_df.copy()
    display.index = range(1, len(display) + 1)  # 1-based ranking

    print()
    print("=" * 50)
    print(f"  SIGNAL REPORT")
    print(f"  Predictions for next trading session")
    print("=" * 50)
    print()
    print(f"  {'Rank':<6}{'Ticker':<8}{'P(UP)':>8}  {'Signal'}")
    print(f"  {'-'*6}{'-'*8}{'-'*8}  {'-'*8}")

    for rank, row in display.iterrows():
        signal = "  BUY" if row["P(UP)"] > threshold else ""
        print(f"  {rank:<6}{row['Ticker']:<8}{row['P(UP)']:>7.2%}  {signal}")

    buys = display[display["P(UP)"] > threshold]
    print()
    print("-" * 50)
    if len(buys) > 0:
        print(f"  ACTIONABLE TRADES ({len(buys)} stocks above {threshold:.0%})")
        print("-" * 50)
        for _, row in buys.iterrows():
            print(f"    -> {row['Ticker']:<6}  P(UP) = {row['P(UP)']:.2%}")
    else:
        print(f"  NO ACTIONABLE TRADES (no stock above {threshold:.0%})")
        print("  Recommendation: stay in cash for this session.")
    print("-" * 50)


if __name__ == "__main__":
    signals = get_signals()
    print_report(signals)
