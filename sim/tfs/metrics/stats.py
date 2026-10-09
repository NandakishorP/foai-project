"""Across-seed statistics: means with 95% confidence intervals.

Each master seed is one independent run, so seeds are the unit of
replication. Ticks and markets within a run are averaged first; the CI is then
taken across seeds with a Student-t interval.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np
from scipy import stats


@dataclass(frozen=True)
class Estimate:
    mean: float
    lo: float  # lower end of the confidence interval
    hi: float
    n: int  # number of (non-missing) values

    def contains(self, value: float) -> bool:
        return self.lo <= value <= self.hi


def mean_ci(values: Iterable[float], level: float = 0.95) -> Estimate:
    """Mean and t-interval, ignoring NaN (e.g. censored time-to-epsilon)."""
    arr = np.asarray(list(values), dtype=float)
    arr = arr[~np.isnan(arr)]
    n = arr.size
    if n == 0:
        return Estimate(math.nan, math.nan, math.nan, 0)
    mean = float(arr.mean())
    if n < 2:
        return Estimate(mean, math.nan, math.nan, n)
    half = float(stats.t.ppf(0.5 + level / 2, df=n - 1) * arr.std(ddof=1) / math.sqrt(n))
    return Estimate(mean, mean - half, mean + half, n)


def rms_ci(mse_values: Iterable[float], level: float = 0.95) -> Estimate:
    """RMS = sqrt(mean MSE), with the CI from square roots of the MSE CI's endpoints.

    The square root is monotone, so this transformed interval keeps its coverage.
    """
    e = mean_ci(mse_values, level)
    return Estimate(
        math.sqrt(e.mean) if e.n else math.nan,
        math.sqrt(max(e.lo, 0.0)) if not math.isnan(e.lo) else math.nan,
        math.sqrt(e.hi) if not math.isnan(e.hi) else math.nan,
        e.n,
    )
