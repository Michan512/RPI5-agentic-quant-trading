"""
Features and label for the XGBoost candidate (Stage D).

Indicator formulas are reused from legacy/training/dataset.py (RSI, MACD,
Bollinger %B, ATR, stochastic), vectorised across all tickers at once.

Changes from the legacy version:
- Timing: features for row T use data up to and including T's close (signal at
  the close, trade at the next open), so no extra shift is needed.
- Scale-free: raw price levels (prev_close, SMA_10, BB_upper, OBV ...) were
  dropped; adjusted price levels drift over time and mean nothing across stocks.
  Everything is a ratio, a return or a bounded oscillator instead.
- Label: the legacy label (close T > close T-1) included the overnight gap that
  can't be traded. The new label is the forward return from the next open
  (T+1) to the open H days later, compared with the cross-sectional median
  that day: 1 = beat the median stock. It is only known at T+1+H, so training
  must drop the last H+1 rows before any cutoff (handled by NaNs here).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

RSI_PERIOD, MACD_FAST, MACD_SLOW, MACD_SIGNAL = 14, 12, 26, 9
BB_PERIOD, BB_STD, ATR_PERIOD, STOCH_K, STOCH_D = 20, 2, 14, 14, 3
WARMUP_ROWS = 400        # enough history for 252-day features and EMA warm-up


def _rsi(close: pd.DataFrame) -> pd.DataFrame:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(RSI_PERIOD, min_periods=RSI_PERIOD).mean()
    loss = (-delta.clip(upper=0)).rolling(RSI_PERIOD, min_periods=RSI_PERIOD).mean()
    return 100 - 100 / (1 + gain / loss)


def _macd_hist(close: pd.DataFrame) -> pd.DataFrame:
    fast = close.ewm(span=MACD_FAST, adjust=False).mean()
    slow = close.ewm(span=MACD_SLOW, adjust=False).mean()
    line = fast - slow
    return line - line.ewm(span=MACD_SIGNAL, adjust=False).mean()


def _wide_features(o, h, l, c, v, market_close, vix_close) -> dict[str, pd.DataFrame]:
    ret1 = c.pct_change(fill_method=None)
    sma = lambda n: c.rolling(n).mean()
    std20 = c.rolling(BB_PERIOD).std()
    prev_c = c.shift(1)
    tr = np.fmax(np.fmax(h - l, (h - prev_c).abs()), (l - prev_c).abs())
    low_k, high_k = l.rolling(STOCH_K).min(), h.rolling(STOCH_K).max()
    stoch_k = 100 * (c - low_k) / (high_k - low_k)

    f = {
        "ret_1": ret1,
        "ret_5": c.pct_change(5, fill_method=None),
        "ret_21": c.pct_change(21, fill_method=None),
        "ret_63": c.pct_change(63, fill_method=None),
        "mom_12_1": c.shift(21) / c.shift(252) - 1,
        "vol_21": ret1.rolling(21).std(),
        "vol_63": ret1.rolling(63).std(),
        "rsi_14": _rsi(c),
        "macd_hist_rel": _macd_hist(c) / c,
        "bb_pctb": (c - (sma(BB_PERIOD) - BB_STD * std20)) / (2 * BB_STD * std20),
        "atr_rel": tr.rolling(ATR_PERIOD, min_periods=ATR_PERIOD).mean() / c,
        "stoch_k": stoch_k,
        "stoch_d": stoch_k.rolling(STOCH_D).mean(),
        "c_sma10": c / sma(10) - 1,
        "c_sma50": c / sma(50) - 1,
        "c_sma200": c / sma(200) - 1,
        "vol_ratio_20": v / v.rolling(20).mean(),
        "gap_today": o / prev_c - 1,
    }
    # Cross-sectional ranks (0..1) among stocks with data that day.
    for name in ("ret_21", "mom_12_1", "vol_63"):
        f[f"{name}_xrank"] = f[name].rank(axis=1, pct=True)

    # Market-wide context, broadcast to every stock.
    m_ret = market_close.pct_change(fill_method=None)
    market = {
        "mkt_ret_5": market_close.pct_change(5, fill_method=None),
        "mkt_ret_21": market_close.pct_change(21, fill_method=None),
        "mkt_c_sma200": market_close / market_close.rolling(200).mean() - 1,
        "mkt_vol_21": m_ret.rolling(21).std(),
        "vix": vix_close,
        "vix_chg_5": vix_close.pct_change(5, fill_method=None),
    }
    for name, s in market.items():
        f[name] = pd.DataFrame(np.repeat(s.to_numpy()[:, None], c.shape[1], axis=1),
                               index=c.index, columns=c.columns)
    return f


FEATURE_COLS = [
    "ret_1", "ret_5", "ret_21", "ret_63", "mom_12_1", "vol_21", "vol_63", "rsi_14",
    "macd_hist_rel", "bb_pctb", "atr_rel", "stoch_k", "stoch_d", "c_sma10", "c_sma50",
    "c_sma200", "vol_ratio_20", "gap_today", "ret_21_xrank", "mom_12_1_xrank",
    "vol_63_xrank", "mkt_ret_5", "mkt_ret_21", "mkt_c_sma200", "mkt_vol_21", "vix", "vix_chg_5",
]


def build_features(field, stocks: list[str], market: str, vix: str) -> pd.DataFrame:
    """
    `field(name)` returns a wide DataFrame (dates x symbols) for open/high/low/close/volume.
    Returns a long DataFrame indexed by (date, ticker) with FEATURE_COLS.
    """
    o, h, l, c, v = (field(n)[stocks] for n in ("open", "high", "low", "close", "volume"))
    wide = _wide_features(o, h, l, c, v, field("close")[market], field("close")[vix])
    # Wide (dates x tickers) per feature -> long (date, ticker) rows. A plain numpy
    # reshape: same values and order as DataFrame.stack(), but ~100x faster.
    cube = np.stack([wide[k].to_numpy(dtype=float) for k in FEATURE_COLS], axis=-1)
    n_dates, n_tickers, n_feats = cube.shape
    index = pd.MultiIndex.from_product([c.index, c.columns], names=["date", "ticker"])
    long = pd.DataFrame(cube.reshape(n_dates * n_tickers, n_feats), index=index, columns=FEATURE_COLS)
    # Only rows where the stock actually traded that day.
    return long[c.notna().to_numpy().ravel()]


def build_labels(field, stocks: list[str], horizon: int) -> pd.Series:
    """1 if open(T+1) -> open(T+1+horizon) beat that day's median stock, else 0. NaN if unknown."""
    o = field("open")[stocks]
    fwd = o.shift(-1 - horizon) / o.shift(-1) - 1
    beat = fwd.sub(fwd.median(axis=1), axis=0)
    label = (beat > 0).astype(float).where(fwd.notna())
    index = pd.MultiIndex.from_product([label.index, label.columns], names=["date", "ticker"])
    return pd.Series(label.to_numpy().ravel(), index=index, name="label")
