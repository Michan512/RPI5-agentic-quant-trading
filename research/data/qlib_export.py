"""
Export the visible (non-holdout) data in the CSV layout Qlib's dump_bin.py expects.

The project's own backtest engine (research/engine) is pure pandas, so the same
strategy code can run on the Raspberry Pi, which can't run Qlib. Qlib remains
available for exploration; this export keeps it fed with the same data, and
holdout rows are never exported.

Usage (from the repo root):
    python -m research.data.qlib_export
Then in WSL:
    ~/qlib-check/.venv/bin/python ~/qlib-check/src/scripts/dump_bin.py dump_all \\
        --data_path <repo>/research/data/cache/qlib_csv --qlib_dir ~/.qlib/qlib_data/us_project \\
        --include_fields open,high,low,close,volume,factor --date_field_name date
"""

from pathlib import Path

import pandas as pd

from research.data.loader import load_panel
from shared.universe import TRADABLE

OUT_DIR = Path(__file__).resolve().parent / "cache" / "qlib_csv"


def export(out_dir: Path = OUT_DIR) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    panel = load_panel(TRADABLE)
    for sym in TRADABLE:
        frame = pd.DataFrame({f: panel[f][sym] for f in ("open", "high", "low", "close", "volume")})
        frame = frame.dropna(subset=["close"])
        frame["factor"] = 1.0           # prices are already split/dividend adjusted
        frame.index.name = "date"
        frame.reset_index().to_csv(out_dir / f"{sym}.csv", index=False)
    print(f"[qlib_export] wrote {len(TRADABLE)} files to {out_dir}")
    return out_dir


if __name__ == "__main__":
    export()
