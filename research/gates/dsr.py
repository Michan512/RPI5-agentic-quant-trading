"""
Deflated Sharpe ratio (Bailey & Lopez de Prado, 2014). Standard library only.

Idea: if you try N strategies, the best one looks good partly by luck. The DSR
is the probability that a strategy's true Sharpe ratio is above the Sharpe you'd
expect from the luckiest of N worthless strategies, also allowing for the
return distribution's skew and fat tails.

All Sharpe ratios here are per period (daily), not annualised.
"""

from __future__ import annotations

import math
from statistics import NormalDist

import numpy as np

EULER_GAMMA = 0.5772156649015329
_N = NormalDist()


def expected_max_sharpe(n_trials: int, sharpe_std: float) -> float:
    """Sharpe the best of n_trials zero-skill strategies would show by luck."""
    if n_trials <= 1:
        return 0.0
    a = _N.inv_cdf(1 - 1 / n_trials)
    b = _N.inv_cdf(1 - 1 / (n_trials * math.e))
    return sharpe_std * ((1 - EULER_GAMMA) * a + EULER_GAMMA * b)


def probabilistic_sharpe(sr: float, sr_benchmark: float, n_obs: int, skew: float, kurtosis: float) -> float:
    """P(true Sharpe > sr_benchmark) given an observed Sharpe `sr` over n_obs periods."""
    denom = 1 - skew * sr + (kurtosis - 1) / 4 * sr ** 2
    if n_obs < 2 or denom <= 0:
        return float("nan")
    return _N.cdf((sr - sr_benchmark) * math.sqrt(n_obs - 1) / math.sqrt(denom))


def deflated_sharpe(returns, n_trials: int, trial_sharpes_daily: list[float],
                    default_sharpe_std: float = 0.5 / math.sqrt(252)) -> dict:
    """
    returns: daily strategy returns on the evaluation period.
    trial_sharpes_daily: daily Sharpe of every trial so far (for the spread of luck).
    """
    r = np.asarray(returns, dtype=float)
    r = r[~np.isnan(r)]
    sd = r.std(ddof=1)
    sr = r.mean() / sd if sd > 0 else 0.0
    z = (r - r.mean()) / sd if sd > 0 else r * 0
    skew = float((z ** 3).mean())
    kurt = float((z ** 4).mean())                 # not excess: normal = 3
    spread = float(np.std(trial_sharpes_daily, ddof=1)) if len(trial_sharpes_daily) >= 2 else default_sharpe_std
    sr0 = expected_max_sharpe(n_trials, spread)
    return {
        "sharpe_daily": sr,
        "sharpe_annual": sr * math.sqrt(252),
        "n_trials": n_trials,
        "luck_benchmark_sharpe_annual": sr0 * math.sqrt(252),
        "skew": skew,
        "kurtosis": kurt,
        "n_obs": int(len(r)),
        "dsr": probabilistic_sharpe(sr, sr0, len(r), skew, kurt),
    }
