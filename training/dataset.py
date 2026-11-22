"""
Load historical CSVs, engineer strictly causal features, and prepare
train/val splits.

CAUSAL CONSTRAINT: All features for Day T must be computable BEFORE the
market opens on Day T.  This means every indicator is computed as-of the
prior day's close and then shifted forward by one row so that row T
contains only information available at T-1 close.

Target: will today's close be higher than yesterday's close?
  target[T] = 1  if  Close[T] > Close[T-1]

Backtest action: buy at Open[T], sell at Close[T].
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config


# ── Technical indicator helpers ────────────────────────────────────────────

def compute_rsi(series: pd.Series, period: int = config.RSI_PERIOD) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def compute_macd(series: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    ema_fast = series.ewm(span=config.MACD_FAST, adjust=False).mean()
    ema_slow = series.ewm(span=config.MACD_SLOW, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=config.MACD_SIGNAL, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def compute_bollinger(series: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    sma = series.rolling(window=config.BB_PERIOD).mean()
    std = series.rolling(window=config.BB_PERIOD).std()
    upper = sma + config.BB_STD * std
    lower = sma - config.BB_STD * std
    pct_b = (series - lower) / (upper - lower)
    return upper, lower, pct_b


def compute_atr(df: pd.DataFrame, period: int = config.ATR_PERIOD) -> pd.Series:
    high_low = df["High"] - df["Low"]
    high_close = (df["High"] - df["Close"].shift(1)).abs()
    low_close = (df["Low"] - df["Close"].shift(1)).abs()
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return true_range.rolling(window=period, min_periods=period).mean()


def compute_stochastic(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    low_min = df["Low"].rolling(window=config.STOCH_K_PERIOD).min()
    high_max = df["High"].rolling(window=config.STOCH_K_PERIOD).max()
    stoch_k = 100 * (df["Close"] - low_min) / (high_max - low_min)
    stoch_d = stoch_k.rolling(window=config.STOCH_D_PERIOD).mean()
    return stoch_k, stoch_d


def compute_obv(df: pd.DataFrame) -> pd.Series:
    direction = np.sign(df["Close"].diff())
    obv = (direction * df["Volume"]).fillna(0).cumsum()
    return obv


# ── Main feature engineering ──────────────────────────────────────────────

def _load_spy_returns(data_dir: Path = config.DATA_DIR) -> pd.Series:
    """Load SPY daily returns as a Series indexed by date."""
    spy_path = data_dir / "SPY.csv"
    spy = pd.read_csv(spy_path, index_col=0, parse_dates=True)
    return spy["Close"].pct_change().rename("spy_return")


def _load_vix(data_dir: Path = config.DATA_DIR) -> pd.DataFrame:
    """Load VIX daily Open and Close as a DataFrame indexed by date."""
    vix_path = data_dir / "^VIX.csv"
    vix = pd.read_csv(vix_path, index_col=0, parse_dates=True)
    return vix[["Open", "Close"]].rename(columns={"Open": "vix_open", "Close": "vix_close"})


def load_and_engineer(ticker: str, spy_returns: pd.Series,
                      vix_df: pd.DataFrame,
                      data_dir: Path = config.DATA_DIR) -> pd.DataFrame:
    path = data_dir / f"{ticker}.csv"
    df = pd.read_csv(path, index_col=0, parse_dates=True)

    # ── Compute raw indicators (as-of each day's close) ──────────────
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

    # Join SPY return and VIX (also computed as-of each day's close)
    df = df.join(spy_returns, how="left")
    df = df.join(vix_df, how="left")

    # ── Shift everything by 1 day to enforce causality ────────────────
    # After shift, row T contains the indicator value from Day T-1,
    # which is known before the market opens on Day T.
    df["prev_close"]    = df["Close"].shift(1)
    df["prev_open"]     = df["Open"].shift(1)
    df["prev_high"]     = df["High"].shift(1)
    df["prev_low"]      = df["Low"].shift(1)
    df["prev_volume"]   = df["Volume"].shift(1)
    df["SMA_10"]        = raw_sma10.shift(1)
    df["SMA_50"]        = raw_sma50.shift(1)
    df["RSI"]           = raw_rsi.shift(1)
    df["daily_return"]  = raw_daily_ret.shift(1)
    df["MACD"]          = raw_macd.shift(1)
    df["MACD_signal"]   = raw_macd_sig.shift(1)
    df["MACD_hist"]     = raw_macd_hist.shift(1)
    df["BB_upper"]      = raw_bb_upper.shift(1)
    df["BB_lower"]      = raw_bb_lower.shift(1)
    df["BB_pctB"]       = raw_bb_pctb.shift(1)
    df["ATR"]           = raw_atr.shift(1)
    df["Stoch_K"]       = raw_stoch_k.shift(1)
    df["Stoch_D"]       = raw_stoch_d.shift(1)
    df["OBV"]           = raw_obv.shift(1)
    df["vol_sma_ratio"] = raw_vol_sma.shift(1)
    df["ROC_10"]        = raw_roc10.shift(1)

    # SPY return lagged by 1 (yesterday's market return)
    df["spy_return_lag_1"] = df["spy_return"].shift(1)

    # VIX features (causal):
    # - vix_open: today's VIX opening price (known before stock market open)
    # - vix_lag_1: yesterday's VIX closing price
    # - vix_change_lag_1: yesterday's VIX intraday change (close - open)
    raw_vix_open = df["vix_open"].copy()
    raw_vix_close = df["vix_close"].copy()
    df["vix_open"]         = raw_vix_open          # same-day open is pre-trade
    df["vix_lag_1"]        = raw_vix_close.shift(1) # yesterday's close
    df["vix_change_lag_1"] = (raw_vix_close - raw_vix_open).shift(1)  # yesterday's intraday VIX move

    # Lagged features: 1/2/3-day lags of yesterday's indicators
    # daily_return_lag_1 = return from 2 days ago, etc.
    for lag in range(1, 4):
        df[f"daily_return_lag_{lag}"] = raw_daily_ret.shift(1 + lag)
        df[f"RSI_lag_{lag}"]         = raw_rsi.shift(1 + lag)
        df[f"MACD_lag_{lag}"]        = raw_macd.shift(1 + lag)

    # ── Target: did today close higher than yesterday? ────────────────
    # Known only AFTER market close on Day T, never used as a feature.
    df["target"] = (df["Close"] > df["Close"].shift(1)).astype(int)

    df.dropna(inplace=True)
    return df


FEATURE_COLS = [
    "prev_close", "prev_open", "prev_high", "prev_low", "prev_volume",
    "SMA_10", "SMA_50", "RSI", "daily_return",
    "MACD", "MACD_signal", "MACD_hist",
    "BB_upper", "BB_lower", "BB_pctB",
    "ATR", "Stoch_K", "Stoch_D", "OBV",
    "vol_sma_ratio", "ROC_10",
    "spy_return_lag_1",
    "vix_open", "vix_lag_1", "vix_change_lag_1",
    "daily_return_lag_1", "daily_return_lag_2", "daily_return_lag_3",
    "RSI_lag_1", "RSI_lag_2", "RSI_lag_3",
    "MACD_lag_1", "MACD_lag_2", "MACD_lag_3",
]


def _build_combined(tickers: list[str] | None = None) -> pd.DataFrame:
    """Load and engineer all tickers into a single DataFrame."""
    tickers = tickers or config.DEFAULT_TICKERS
    spy_returns = _load_spy_returns()
    vix_df = _load_vix()
    frames = []
    for t in tickers:
        try:
            df = load_and_engineer(t, spy_returns, vix_df)
            df["ticker"] = t
            frames.append(df)
        except FileNotFoundError:
            print(f"[dataset] {t}.csv not found - skipping")

    if not frames:
        raise RuntimeError("No data files found. Run data/fetcher.py first.")

    combined = pd.concat(frames)
    combined["date"] = combined.index
    combined.sort_values("date", inplace=True)
    combined.reset_index(drop=True, inplace=True)
    return combined


def prepare_datasets(tickers: list[str] | None = None):
    combined = _build_combined(tickers)

    X = combined[FEATURE_COLS].values
    y = combined["target"].values

    split_idx = int(len(X) * config.TRAIN_SPLIT)
    X_train, X_val = X[:split_idx], X[split_idx:]
    y_train, y_val = y[:split_idx], y[split_idx:]

    scaler = StandardScaler()
    X_train = scaler.fit_transform(X_train)
    X_val = scaler.transform(X_val)

    print(f"[dataset] Features: {len(FEATURE_COLS)}  |  "
          f"Train samples: {len(X_train)}  |  Val samples: {len(X_val)}")
    return X_train, y_train, X_val, y_val, scaler


def prepare_backtest_data(tickers: list[str] | None = None):
    """Return scaled val features, val labels, raw val prices DataFrame, and scaler."""
    combined = _build_combined(tickers)

    split_idx = int(len(combined) * config.TRAIN_SPLIT)
    train_df = combined.iloc[:split_idx]
    val_df = combined.iloc[split_idx:].copy()

    scaler = StandardScaler()
    scaler.fit(train_df[FEATURE_COLS].values)
    X_val = scaler.transform(val_df[FEATURE_COLS].values)
    y_val = val_df["target"].values

    return X_val, y_val, val_df, scaler


def prepare_datasets_by_date(train_end: str, test_start: str, test_end: str,
                             tickers: list[str] | None = None):
    """Split by explicit date boundaries. Returns train/test arrays + scaler."""
    combined = _build_combined(tickers)
    train_mask = combined["date"] < train_end
    test_mask = (combined["date"] >= test_start) & (combined["date"] <= test_end)

    train_df = combined[train_mask]
    test_df = combined[test_mask].copy()

    scaler = StandardScaler()
    X_train = scaler.fit_transform(train_df[FEATURE_COLS].values)
    y_train = train_df["target"].values
    X_test = scaler.transform(test_df[FEATURE_COLS].values)
    y_test = test_df["target"].values

    print(f"[dataset] Features: {len(FEATURE_COLS)}  |  "
          f"Train: {len(X_train)} (< {train_end})  |  "
          f"Test: {len(X_test)} ({test_start} to {test_end})")
    return X_train, y_train, X_test, y_test, test_df, scaler
