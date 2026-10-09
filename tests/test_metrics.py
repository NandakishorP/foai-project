import math

import numpy as np
import pytest

from tfs.metrics.accuracy import brier_scores, decompose, time_to_epsilon
from tfs.metrics.stats import mean_ci, rms_ci


def test_decompose_known_values() -> None:
    price = np.array([0.5, 0.6])
    p_avail = np.array([0.5, 0.5])
    p_full = np.array([0.7, 0.5])
    d = decompose(price, p_full, p_avail)
    assert d.truth_mse == pytest.approx((0.04 + 0.01) / 2)
    assert d.aggregation_mse == pytest.approx(0.01 / 2)
    assert d.participation_mse == pytest.approx(0.04 / 2)
    assert d.cross_term == pytest.approx(0.0)


def test_brier() -> None:
    final, mean = brier_scores(np.array([0.5, 0.9]), 1)
    assert final == pytest.approx(0.01)
    assert mean == pytest.approx((0.25 + 0.01) / 2)


def test_time_to_epsilon_settles_and_stays() -> None:
    p_avail = np.full(10, 0.5)
    price = np.array([0.5, 0.5, 0.9, 0.52, 0.8, 0.51, 0.5, 0.5, 0.5, 0.5])
    # shock at tick 2: within eps (0.05) at 3, out again at 4, settled from 5 onward -> 3 ticks after the shock
    assert time_to_epsilon(price, p_avail, [2], 0.05) == [3]


def test_time_to_epsilon_immediate_and_censored() -> None:
    p_avail = np.full(6, 0.5)
    assert time_to_epsilon(np.full(6, 0.5), p_avail, [1], 0.05) == [0]
    never = np.array([0.5, 0.9, 0.9, 0.9, 0.9, 0.9])
    assert time_to_epsilon(never, p_avail, [1], 0.05) == [None]


def test_time_to_epsilon_windows_end_at_next_shock() -> None:
    p_avail = np.full(8, 0.5)
    price = np.array([0.5, 0.9, 0.5, 0.5, 0.9, 0.9, 0.5, 0.5])
    assert time_to_epsilon(price, p_avail, [1, 4], 0.05) == [1, 2]


def test_mean_ci_coverage() -> None:
    """A 95% interval should contain the true mean ~95% of the time."""
    rng = np.random.default_rng(0)
    hits = sum(mean_ci(rng.normal(3.0, 2.0, size=30)).contains(3.0) for _ in range(2000))
    assert hits / 2000 == pytest.approx(0.95, abs=0.015)


def test_mean_ci_ignores_nan_and_handles_tiny_samples() -> None:
    e = mean_ci([1.0, math.nan, 3.0])
    assert e.mean == 2.0 and e.n == 2
    single = mean_ci([5.0])
    assert single.mean == 5.0 and math.isnan(single.lo)
    assert math.isnan(mean_ci([]).mean)


def test_rms_ci_is_sqrt_of_mse_ci() -> None:
    mse = [0.04, 0.09, 0.01, 0.16]
    e, r = mean_ci(mse), rms_ci(mse)
    assert r.mean == pytest.approx(math.sqrt(e.mean))
    assert r.hi == pytest.approx(math.sqrt(e.hi))
    assert r.lo == pytest.approx(math.sqrt(max(e.lo, 0.0)))


def test_research_share_priced_is_a_ratio_of_sums() -> None:
    from tfs.experiments.runner import research_share_priced

    assert research_share_priced([0.0, 0.0], [0.1, 0.3])[0] == 1.0  # price equals p*_avail
    assert research_share_priced([0.1, 0.3], [0.1, 0.3])[0] == 0.0  # no better than ignoring research
    # pooled: 1 - (0.01 + 0.1) / (0.02 + 1.0); a mean of per-run ratios would give 1 - (0.5 + 0.1) / 2
    share, num, den = research_share_priced([0.01, 0.1], [0.02, 1.0])
    assert share == pytest.approx(1 - 0.11 / 1.02)
    assert (num, den) == (pytest.approx(0.055), pytest.approx(0.51))
