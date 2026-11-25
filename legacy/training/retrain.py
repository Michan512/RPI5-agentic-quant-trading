"""
Continuous re-training pipeline.

Steps:
  1. For every existing raw CSV in data/ (the 20 stocks, SPY, and VIX),
     find the last date already on disk.
  2. Download any missing daily bars from that date up to today and append
     them to the existing CSV, expanding the historical database.
  3. Regenerate the strictly-causal features over the expanded dataset and
     re-train the XGBoost model, overwriting the saved model in models/.

Run:  python training/retrain.py
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config
from training.train_model import train

# The full universe persisted on disk: the default tickers (which include SPY)
# plus the VIX index, stored as ^VIX.csv.
RETRAIN_TICKERS = list(config.DEFAULT_TICKERS) + ["^VIX"]


def _last_date(csv_path: Path) -> pd.Timestamp | None:
    """Return the most recent date in an existing ticker CSV, or None."""
    df = pd.read_csv(csv_path, index_col=0, parse_dates=True)
    if df.empty:
        return None
    return df.index.max()


def update_ticker(ticker: str, data_dir: Path = config.DATA_DIR) -> int:
    """Append any missing daily bars for *ticker*. Returns rows added."""
    path = data_dir / f"{ticker}.csv"
    today = datetime.today().date()

    if not path.exists():
        # No history yet -> pull the full configured window.
        print(f"[retrain] {ticker}: no existing CSV, fetching full history")
        start = today - timedelta(days=config.DATA_PERIOD_YEARS * 365)
        existing = None
    else:
        last = _last_date(path)
        if last is None:
            start = today - timedelta(days=config.DATA_PERIOD_YEARS * 365)
            existing = None
        else:
            start = last.date() + timedelta(days=1)
            existing = pd.read_csv(path, index_col=0, parse_dates=True)
            if start > today:
                print(f"[retrain] {ticker}: up to date (last {last.date()})")
                return 0

    # yfinance 'end' is exclusive, so add a day to include today's bar.
    end = today + timedelta(days=1)
    print(f"[retrain] {ticker}: fetching {start} -> {today}")
    new = yf.download(ticker, start=start.strftime("%Y-%m-%d"),
                      end=end.strftime("%Y-%m-%d"), progress=False)

    if new.empty:
        print(f"[retrain] {ticker}: no new bars returned")
        return 0

    if isinstance(new.columns, pd.MultiIndex):
        new.columns = new.columns.get_level_values(0)
    new = new[["Open", "High", "Low", "Close", "Volume"]]
    new.index.name = "Date"

    if existing is not None:
        # Keep only rows strictly newer than what we already have, then merge.
        new = new[new.index > existing.index.max()]
        if new.empty:
            print(f"[retrain] {ticker}: already current")
            return 0
        combined = pd.concat([existing, new])
    else:
        combined = new

    combined = combined[~combined.index.duplicated(keep="last")].sort_index()
    combined.index.name = "Date"
    combined.to_csv(path)
    print(f"[retrain] {ticker}: +{len(new)} rows (now {len(combined)} total)")
    return len(new)


def refresh_data(tickers: list[str] | None = None) -> int:
    """Update every ticker CSV. Returns total rows added across the universe."""
    tickers = tickers or RETRAIN_TICKERS
    total = 0
    for t in tickers:
        try:
            total += update_ticker(t)
        except Exception as exc:  # network / parsing issues shouldn't abort all
            print(f"[retrain] {t}: ERROR {exc}")
    print(f"\n[retrain] Data refresh complete: {total} new rows added\n")
    return total


def main() -> None:
    print("=" * 60)
    print("  RE-TRAINING PIPELINE")
    print("=" * 60)

    refresh_data()

    print("[retrain] Regenerating features and re-training XGBoost model...\n")
    val_acc, val_logloss = train()

    print("\n" + "=" * 60)
    print(f"  Model updated -> {config.MODELS_DIR / 'trading_model_xgb.json'}")
    print(f"  Val accuracy : {val_acc:.4f}   Val log-loss: {val_logloss:.4f}")
    print("=" * 60)


if __name__ == "__main__":
    main()
