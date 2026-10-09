"""Per-market accuracy metrics (SPEC §7 glossary, DECISIONS D-001).

Truth lost is the mean squared error of the market price against p*_full. It
splits additively into aggregation loss and participation loss:

    (p − p*_full)² = (p − p*_avail)² + (p*_avail − p*_full)² + 2 (p − p*_avail)(p*_avail − p*_full)

The last (cross) term is zero *in expectation across seeds*, but not in any
single run, so we keep it per run and check its average (tests/test_decomposition.py).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Decomposition:
    truth_mse: float  # mean over ticks of (p − p*_full)²
    aggregation_mse: float  # mean over ticks of (p − p*_avail)²
    participation_mse: float  # mean over ticks of (p*_avail − p*_full)²
    cross_term: float  # mean over ticks of (p − p*_avail)(p*_avail − p*_full); truth = agg + part + 2·cross


def decompose(price: np.ndarray, p_full: np.ndarray, p_avail: np.ndarray) -> Decomposition:
    aggregation_gap = price - p_avail
    participation_gap = p_avail - p_full
    return Decomposition(
        truth_mse=float(np.mean((price - p_full) ** 2)),
        aggregation_mse=float(np.mean(aggregation_gap**2)),
        participation_mse=float(np.mean(participation_gap**2)),
        cross_term=float(np.mean(aggregation_gap * participation_gap)),
    )


def brier_scores(price: np.ndarray, y: int) -> tuple[float, float]:
    """(Brier score of the closing price, Brier score averaged over all ticks)."""
    return float((price[-1] - y) ** 2), float(np.mean((price - y) ** 2))


def time_to_epsilon(
    price: np.ndarray, p_avail: np.ndarray, shock_ticks: Sequence[int], epsilon: float
) -> list[int | None]:
    """Ticks after each shock until the price is within epsilon of p*_avail *and stays there*.

    "Stays there" means until the next shock or the end of the market. A shock
    whose window never settles is censored and reported as None. Callers must
    report the censored share, not drop it silently.
    """
    within = np.abs(price - p_avail) < epsilon
    bounds = sorted(shock_ticks) + [len(price)]
    result: list[int | None] = []
    for start, end in zip(bounds[:-1], bounds[1:]):
        window = within[start:end]
        if not window[-1]:
            result.append(None)
            continue
        # last tick in the window that was outside epsilon; settled from the tick after it
        outside = np.flatnonzero(~window)
        result.append(0 if outside.size == 0 else int(outside[-1]) + 1)
    return result
