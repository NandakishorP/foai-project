"""Paired comparisons between a predator run and its no-predator twin (PREREGISTRATION rules 1–4).

Both arms run on the same master seeds, so seed i of one arm and seed i of
the other share every random draw that does not depend on prices. The
statistics are ratios of sums over seeds. Their 95% CIs come from a paired
bootstrap: resample seeds (keeping each pair together) 10,000 times with a
fixed bootstrap seed, then take percentiles.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

RESAMPLES = 10_000
BOOTSTRAP_SEED = 0


@dataclass(frozen=True)
class Interval:
    point: float
    lo: float
    hi: float


def paired_bootstrap(
    statistic: Callable[[np.ndarray], np.ndarray], n_seeds: int, resamples: int = RESAMPLES
) -> tuple[float, float, float]:
    """Point estimate and 95% percentile CI of a statistic of resampled seed indices.

    `statistic` receives an integer array of shape (k, n_seeds) of seed indices
    (each row one resample) and returns k values. Row 0 is the identity, the
    point estimate.
    """
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    identity = np.arange(n_seeds)[None, :]
    point = float(statistic(identity)[0])
    draws = statistic(rng.integers(0, n_seeds, size=(resamples, n_seeds)))
    lo, hi = np.percentile(draws, [2.5, 97.5])
    return point, float(lo), float(hi)


def rms_change(truth_mse_pred: np.ndarray, truth_mse_base: np.ndarray) -> Interval:
    """Δ = RMS_predators / RMS_baseline − 1, with RMS from pooled MSE (rule 4)."""
    pred, base = np.asarray(truth_mse_pred), np.asarray(truth_mse_base)
    return Interval(*paired_bootstrap(lambda idx: np.sqrt(pred[idx].sum(1) / base[idx].sum(1)) - 1.0, len(pred)))


def leakage_ratio(informed_pnl_pred: np.ndarray, informed_pnl_base: np.ndarray) -> Interval:
    """L = 1 − Σ informed PnL with predators / Σ informed PnL without: the share of the informed edge lost."""
    pred, base = np.asarray(informed_pnl_pred), np.asarray(informed_pnl_base)
    return Interval(*paired_bootstrap(lambda idx: 1.0 - pred[idx].sum(1) / base[idx].sum(1), len(pred)))


def participation_gap(participation_base: np.ndarray, participation_pred: np.ndarray) -> Interval:
    """G = participation without predators − with predators, in percentage points."""
    pred, base = np.asarray(participation_pred), np.asarray(participation_base)
    return Interval(*paired_bootstrap(lambda idx: 100.0 * (base[idx].mean(1) - pred[idx].mean(1)), len(pred)))


def mean_difference(pred: np.ndarray, base: np.ndarray) -> Interval:
    """Paired mean difference (predators − baseline), for descriptive reporting."""
    p, b = np.asarray(pred), np.asarray(base)
    return Interval(*paired_bootstrap(lambda idx: p[idx].mean(1) - b[idx].mean(1), len(p)))
