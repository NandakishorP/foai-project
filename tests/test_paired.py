import numpy as np
import pytest

from tfs.metrics.paired import Interval, leakage_ratio, participation_gap, rms_change


def test_statistics_are_ratios_of_sums_not_means_of_ratios() -> None:
    base = np.array([1.0, 100.0])
    pred = np.array([2.0, 100.0])
    # ratio of sums: 102/101; a mean of per-seed ratios would give (2 + 1)/2
    assert leakage_ratio(pred, base).point == pytest.approx(1 - 102 / 101)
    assert rms_change(pred, base).point == pytest.approx(np.sqrt(102 / 101) - 1)


def test_participation_gap_in_percentage_points() -> None:
    gap = participation_gap(np.array([0.6, 0.5]), np.array([0.3, 0.3]))
    assert gap.point == pytest.approx(25.0)


def test_bootstrap_is_deterministic_and_brackets_the_point() -> None:
    rng = np.random.default_rng(1)
    base = rng.uniform(1, 2, 200)
    pred = base * rng.uniform(1.1, 1.3, 200)
    a, b = rms_change(pred, base), rms_change(pred, base)
    assert a == b
    assert a.lo < a.point < a.hi


def test_paired_bootstrap_coverage() -> None:
    """Across many synthetic paired data sets, the 95% CI for the leakage ratio covers the truth ~95% of the time."""
    rng = np.random.default_rng(7)
    true_l = 0.3
    hits = 0
    trials = 300
    for _ in range(trials):
        base = rng.normal(10.0, 3.0, 200)
        pred = (1 - true_l) * base + rng.normal(0.0, 2.0, 200)
        iv: Interval = leakage_ratio(pred, base)
        hits += iv.lo <= true_l <= iv.hi
    assert hits / trials == pytest.approx(0.95, abs=0.04)
