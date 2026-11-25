"""
Download and incrementally update daily OHLCV data for the universe (yfinance).

Reused from the legacy project: the incremental "find last date, fetch only
newer bars, de-duplicate on append" logic from legacy/training/retrain.py.

Changed:
- Prices are fully adjusted (splits + dividends). An adjusted history changes
  every time a stock pays a dividend or splits, so blindly appending new bars
  would splice two different adjustment bases together. Each update therefore
  re-downloads a short overlap window; if the overlap no longer matches what is
  stored, the whole history for that symbol is re-downloaded.
- A bar for "today" is dropped if the US market hasn't closed yet (partial bar).
- Corporate actions (dividends, splits) are saved for the data checks.
- History starts at research/data/splits.DATA_START.

yfinance is unofficial: it can rate-limit, change format, or return gaps
without warning. Fine for research; the live side needs a sturdier feed.

Usage (from the repo root):
    python -m research.data.fetcher            # update every symbol
    python -m research.data.fetcher AAPL SPY   # update some symbols
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

from research.data.splits import DATA_START
from shared.universe import ALL_SYMBOLS

RAW_DIR = Path(__file__).resolve().parent / "raw"
ACTIONS_DIR = RAW_DIR / "actions"
MANIFEST = RAW_DIR / "manifest.json"
COLUMNS = ["Open", "High", "Low", "Close", "Volume"]
OVERLAP_DAYS = 10            # calendar days re-downloaded to detect re-adjustment
REL_TOL = 1e-5               # overlap mismatch tolerance


def csv_path(symbol: str) -> Path:
    return RAW_DIR / f"{symbol}.csv"


def _download(symbol: str, start, end) -> pd.DataFrame:
    df = yf.download(symbol, start=pd.Timestamp(start).strftime("%Y-%m-%d"),
                     end=pd.Timestamp(end).strftime("%Y-%m-%d"),
                     progress=False, auto_adjust=True)
    if df.empty:
        return df
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df[COLUMNS].copy()
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    df.index.name = "Date"
    return _drop_partial_today(df)


def _drop_partial_today(df: pd.DataFrame) -> pd.DataFrame:
    """Remove today's bar if the US session hasn't finished (16:00 ET + buffer)."""
    now_et = datetime.now(ZoneInfo("America/New_York"))
    today = pd.Timestamp(now_et.date())
    closed = (now_et.hour, now_et.minute) >= (16, 30)
    if not closed and len(df) and df.index[-1] >= today:
        df = df[df.index < today]
    return df


def _read(symbol: str) -> pd.DataFrame | None:
    p = csv_path(symbol)
    if not p.exists():
        return None
    df = pd.read_csv(p, index_col=0, parse_dates=True)
    return None if df.empty else df


def _write(symbol: str, df: pd.DataFrame) -> None:
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df.index.name = "Date"
    df.to_csv(csv_path(symbol))


def _manifest() -> dict:
    return json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}


def _save_actions(symbol: str) -> None:
    if symbol.startswith("^"):
        return
    try:
        actions = yf.Ticker(symbol).actions
    except Exception as exc:  # actions are for checks only; don't fail the update
        print(f"[fetcher] {symbol}: could not fetch corporate actions ({exc})")
        return
    if actions is None or actions.empty:
        return
    actions.index = pd.to_datetime(actions.index).tz_localize(None).normalize()
    ACTIONS_DIR.mkdir(parents=True, exist_ok=True)
    actions.to_csv(ACTIONS_DIR / f"{symbol}.csv")


def full_refresh(symbol: str) -> int:
    end = datetime.today() + timedelta(days=1)
    df = _download(symbol, DATA_START, end)
    if df.empty:
        print(f"[fetcher] {symbol}: WARNING no data returned")
        return 0
    _write(symbol, df)
    m = _manifest()
    m[symbol] = {"history_start": str(DATA_START.date()),
                 "last_full_refresh": datetime.today().strftime("%Y-%m-%d")}
    MANIFEST.write_text(json.dumps(m, indent=2, sort_keys=True))
    print(f"[fetcher] {symbol}: full history {df.index[0].date()} -> {df.index[-1].date()} ({len(df)} rows)")
    return len(df)


def update_symbol(symbol: str) -> int:
    """Bring one symbol up to date. Returns the number of new rows written."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    existing = _read(symbol)
    meta = _manifest().get(symbol, {})

    # No file, or a file from before history started at DATA_START -> full download.
    if existing is None or meta.get("history_start") != str(DATA_START.date()):
        n = full_refresh(symbol)
        _save_actions(symbol)
        return n

    last = existing.index.max()
    end = datetime.today() + timedelta(days=1)
    fresh = _download(symbol, last - timedelta(days=OVERLAP_DAYS), end)
    if fresh.empty:
        print(f"[fetcher] {symbol}: no bars returned (up to date or source problem)")
        return 0

    overlap = existing.index.intersection(fresh.index)
    if len(overlap):
        old = existing.loc[overlap, "Close"].astype(float)
        new = fresh.loc[overlap, "Close"].astype(float)
        if ((old - new).abs() / old).max() > REL_TOL:
            print(f"[fetcher] {symbol}: adjustment changed (dividend/split) -> re-downloading history")
            n = full_refresh(symbol)
            _save_actions(symbol)
            return n

    new_rows = fresh[fresh.index > last]
    if new_rows.empty:
        print(f"[fetcher] {symbol}: up to date (last {last.date()})")
        return 0
    _write(symbol, pd.concat([existing, new_rows]))
    print(f"[fetcher] {symbol}: +{len(new_rows)} rows (last {new_rows.index[-1].date()})")
    return len(new_rows)


def update_all(symbols=None) -> int:
    total = 0
    for s in symbols or ALL_SYMBOLS:
        try:
            total += update_symbol(s)
        except Exception as exc:  # one bad symbol shouldn't stop the rest
            print(f"[fetcher] {s}: ERROR {exc}")
    print(f"[fetcher] done: {total} rows written")
    return total


if __name__ == "__main__":
    update_all(sys.argv[1:] or None)
