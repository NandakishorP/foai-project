import math

import numpy as np
import pytest
from scipy.special import expit
from scipy.stats import norm

from tfs.core.config import SimConfig, replace_in
from tfs.core.information import (
    draw_forecaster_traits,
    generate_tape,
    p_star_avail,
    p_star_full,
    sigma_for_nats,
    signal_llr,
)
from tfs.core.rng import RngFactory


def _tape(cfg: SimConfig, seed: int, market: int = 0):
    rngs = RngFactory(seed)
    return generate_tape(cfg, draw_forecaster_traits(cfg, rngs), rngs, market)


def test_llr_matches_gaussian_density_ratio() -> None:
    mu, sigma = 0.7, 2.3
    for s in (-3.0, -0.1, 0.0, 1.5):
        direct = math.log(norm.pdf(s, mu, sigma) / norm.pdf(s, -mu, sigma))
        assert signal_llr(s, mu, sigma) == pytest.approx(direct)


def test_sigma_for_nats_delivers_expected_information() -> None:
    """Many signals with the derived sigma carry `nats` expected LLR in total."""
    mu, nats, n = 1.0, 2.0, 10
    sigma = sigma_for_nats(nats, n, mu)
    rng = np.random.default_rng(0)
    s = mu + sigma * rng.standard_normal((20000, n))  # Y = 1
    total = signal_llr(s, mu, sigma).sum(axis=1)
    assert total.mean() == pytest.approx(nats, rel=0.03)


def test_tape_information_matches_config(base_config: SimConfig) -> None:
    """Average total LLR at close, signed by Y, equals the configured nats (public + shock + private)."""
    cfg = base_config
    info = cfg.information
    totals, expected_private = [], []
    for seed in range(1500):
        rngs = RngFactory(seed)
        traits = draw_forecaster_traits(cfg, rngs)
        tape = generate_tape(cfg, traits, rngs, 0)
        sign = 1 if tape.y == 1 else -1
        totals.append(sign * (tape.public_llr.sum() + tape.private_llr.sum()))
        expected_private.append(sum(t.nats for t in traits))
    expected = info.public.expected_nats + sum(s.nats for s in info.shocks) + float(np.mean(expected_private))
    se = np.std(totals) / math.sqrt(len(totals))
    assert abs(np.mean(totals) - expected) < 4 * se


def test_p_star_full_is_calibrated(base_config: SimConfig) -> None:
    """When p*_full says 70%, Y=1 about 70% of the time: the Bayesian code is right."""
    preds, outcomes = [], []
    for seed in range(3000):
        tape = _tape(base_config, seed)
        p = p_star_full(tape)
        for t in (20, 60, 100, 150):
            preds.append(p[t])
            outcomes.append(tape.y)
    preds_arr, y_arr = np.array(preds), np.array(outcomes)
    bins = np.linspace(0, 1, 11)
    for lo, hi in zip(bins[:-1], bins[1:]):
        mask = (preds_arr >= lo) & (preds_arr < hi)
        if mask.sum() < 200:
            continue
        freq, mean_pred = y_arr[mask].mean(), preds_arr[mask].mean()
        se = math.sqrt(mean_pred * (1 - mean_pred) / mask.sum())
        # samples within a seed are correlated, so allow a generous 4 SE + 0.02
        assert abs(freq - mean_pred) < 4 * se + 0.02, (lo, hi, freq, mean_pred)


def test_p_star_avail_limits(base_config: SimConfig) -> None:
    tape = _tape(base_config, 5)
    n = tape.private_llr.shape[0]
    np.testing.assert_allclose(p_star_avail(tape, range(n)), p_star_full(tape))
    public_only = expit(tape.prior_logodds + np.cumsum(tape.public_llr))
    np.testing.assert_allclose(p_star_avail(tape, []), public_only)


def test_tape_is_deterministic(base_config: SimConfig) -> None:
    a, b = _tape(base_config, 3), _tape(base_config, 3)
    assert a.y == b.y
    np.testing.assert_array_equal(a.public_llr, b.public_llr)
    np.testing.assert_array_equal(a.private_llr, b.private_llr)


def test_adding_forecasters_keeps_existing_signals(base_config: SimConfig) -> None:
    """Common random numbers: forecaster 0's signals do not depend on how many forecasters exist."""
    small = replace_in(base_config, "agents.forecasters.count", 3)
    a, b = _tape(small, 9), _tape(base_config, 9)
    np.testing.assert_array_equal(a.private_llr[0], b.private_llr[0])
    np.testing.assert_array_equal(a.public_llr, b.public_llr)
