"""
Fetch historical daily OHLCV data via yfinance and save as CSV.
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config


def fetch_ticker(ticker: str, years: int = config.DATA_PERIOD_YEARS) -> pd.DataFrame:
    """Download daily OHLCV data for *ticker* covering the last *years* years."""
    end = datetime.today()
    start = end - timedelta(days=years * 365)
    print(f"[fetcher] Downloading {ticker}  {start.date()} -> {end.date()}")
    df = yf.download(ticker, start=start.strftime("%Y-%m-%d"),
                      end=end.strftime("%Y-%m-%d"), progress=False)
    if df.empty:
        print(f"[fetcher] WARNING: No data returned for {ticker}")
        return df
    # Flatten multi-level columns if present
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df[["Open", "High", "Low", "Close", "Volume"]]
    return df


def save_ticker(ticker: str, df: pd.DataFrame, out_dir: Path = config.DATA_DIR) -> Path:
    """Persist a ticker DataFrame to CSV and return the file path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{ticker}.csv"
    df.to_csv(path)
    print(f"[fetcher] Saved {len(df)} rows -> {path}")
    return path


def fetch_and_save(tickers: list[str] | None = None) -> list[Path]:
    """Convenience wrapper: download + save for a list of tickers."""
    tickers = tickers or config.DEFAULT_TICKERS
    paths = []
    for t in tickers:
        df = fetch_ticker(t)
        if not df.empty:
            paths.append(save_ticker(t, df))
    return paths


if __name__ == "__main__":
    # Allow CLI override: python fetcher.py AAPL TSLA
    tickers = sys.argv[1:] or None
    fetch_and_save(tickers)
