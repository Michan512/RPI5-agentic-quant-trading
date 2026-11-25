"""Small synthetic price panels for engine tests."""

import numpy as np
import pandas as pd


def synthetic_panel(symbols=("SPY", "AAPL", "SHY"), days=300, seed=0, flat=False):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2010-01-04", periods=days)
    closes = {}
    for s in symbols:
        r = np.zeros(days) if flat else rng.normal(0.0005, 0.01, days)
        closes[s] = 100 * np.exp(np.cumsum(r))
    close = pd.DataFrame(closes, index=idx)
    open_ = close.shift(1).fillna(close.iloc[0]) * (1 if flat else 1.001)
    return {
        "close": close,
        "open": open_,
        "high": np.maximum(open_, close) * (1 if flat else 1.005),
        "low": np.minimum(open_, close) * (1 if flat else 0.995),
        "volume": pd.DataFrame(1e6, index=idx, columns=list(symbols)),
    }
