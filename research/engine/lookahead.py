"""
Look-ahead test: altering prices after date T must not change a strategy's output for T.

For each test date T, compute weights on the real data, then scramble every
price after T (random multipliers, shuffled rows) and compute weights again with
a *fresh* strategy instance. Any difference means the strategy saw the future.
"""

from __future__ import annotations

from typing import Callable

import numpy as np
import pandas as pd

from shared.strategy import PriceView, Strategy, validate_weights


def _scramble_after(panel: dict[str, pd.DataFrame], T: pd.Timestamp, seed: int) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    out = {}
    for name, df in panel.items():
        df = df.astype(float)          # copy, and allow float multipliers on integer volume
        after = df.index > T
        n = int(after.sum())
        if n:
            vals = df.loc[after].to_numpy(dtype=float)
            vals = vals[rng.permutation(n)] * rng.uniform(0.3, 3.0, size=vals.shape)
            df.loc[after] = vals
        out[name] = df
    return out


def check_no_lookahead(make_strategy: Callable[[], Strategy], panel: dict[str, pd.DataFrame],
                       test_dates, seed: int = 0, atol: float = 1e-12) -> list[str]:
    """Return a list of failure messages (empty list = passed)."""
    failures = []
    for k, T in enumerate(test_dates):
        T = pd.Timestamp(T)
        real = validate_weights(make_strategy().target_weights(PriceView(panel, T)))
        fake_panel = _scramble_after(panel, T, seed + k)
        fake = validate_weights(make_strategy().target_weights(PriceView(fake_panel, T)))
        idx = real.index.union(fake.index)
        diff = (real.reindex(idx).fillna(0) - fake.reindex(idx).fillna(0)).abs()
        if (diff > atol).any():
            failures.append(f"{T.date()}: weights changed when future prices changed: "
                            f"{diff[diff > atol].round(6).to_dict()}")
    return failures
