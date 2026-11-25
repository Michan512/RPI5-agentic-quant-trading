"""
Load price data as a panel: {field: DataFrame(index=trading dates, columns=symbols)}.

HOLDOUT LOCK
------------
By default every row on or after splits.HOLDOUT_START is removed before the
data leaves this module. Asking for holdout rows (include_holdout=True) raises
HoldoutAccessError unless the *direct caller* is a module inside research.gates.
tests/test_holdout_lock.py also scans the code base to make sure nothing else
reads the raw files directly.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pandas as pd

from research.data import splits
from shared.universe import ALL_SYMBOLS, etf

RAW_DIR = Path(__file__).resolve().parent / "raw"
FIELDS = ("open", "high", "low", "close", "volume")
_GATE_PREFIX = "research.gates"


class HoldoutAccessError(PermissionError):
    """Raised when non-gate code asks for holdout data."""


def _direct_caller_module() -> str:
    # stack()[0] = this function, [1] = load_panel, [2] = whoever called load_panel
    frame = inspect.stack()[2].frame
    return frame.f_globals.get("__name__", "")


def _read_symbol(symbol: str, raw_dir: Path) -> pd.DataFrame:
    path = raw_dir / f"{symbol}.csv"
    if not path.exists():
        raise FileNotFoundError(f"{path} missing; run: python -m research.data.fetcher")
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    df.columns = [c.lower() for c in df.columns]
    return df


def load_panel(symbols=None, include_holdout: bool = False,
               raw_dir: Path = RAW_DIR) -> dict[str, pd.DataFrame]:
    """
    Return {field: DataFrame} on the trading calendar of the broad index ETF.

    Missing bars stay NaN (e.g. a stock before its IPO). Rows on/after
    HOLDOUT_START are dropped unless the direct caller is in research.gates.
    """
    if include_holdout:
        caller = _direct_caller_module()
        if not caller.startswith(_GATE_PREFIX):
            raise HoldoutAccessError(
                f"holdout data is locked; only {_GATE_PREFIX}.* may read it (caller: {caller!r})")

    symbols = list(symbols or ALL_SYMBOLS)
    calendar_symbol = etf("broad_index")
    frames = {s: _read_symbol(s, raw_dir) for s in set(symbols) | {calendar_symbol}}
    calendar = frames[calendar_symbol].index
    calendar = calendar[calendar >= splits.DATA_START]
    if not include_holdout:
        calendar = calendar[calendar < splits.HOLDOUT_START]

    panel = {}
    for field in FIELDS:
        panel[field] = pd.DataFrame(
            {s: frames[s][field].reindex(calendar) for s in symbols}, index=calendar)
        panel[field].index.name = "date"
    return panel


def tail_date(panel: dict[str, pd.DataFrame]) -> pd.Timestamp:
    return panel["close"].index[-1]
