import math

import numpy as np
import pytest
from scipy.special import expit
from scipy.stats import multivariate_normal, norm

from tfs.core.config import SimConfig, replace_in
from tfs.core.information import (
    ResearchNoise,
    generate_tape,
    p_star_avail,
    p_star_full,
    research_noise,
    sigma_for_nats,
    signal_llr,
)
from tfs.core.rng import RngFactory


def _with_rho(cfg: SimConfig, rho: float) -> SimConfig:
    return replace_in(cfg, "information.private.rho", rho)


def _tape(cfg: SimConfig, seed: int, market: int = 0):
    return generate_tape(cfg, RngFactory(seed), market)


# ------------------------------------------------------------- single signals


def test_llr_matches_gaussian_density_ratio() -> None:
    mu, sigma = 0.7, 2.3
    for s in (-3.0, -0.1, 0.0, 1.5):
        direct = math.log(norm.pdf(s, mu, sigma) / norm.pdf(s, -mu, sigma))
        assert signal_llr(s, mu, sigma) == pytest.approx(direct)


def test_sigma_for_nats_delivers_expected_information() -> None:
    mu, nats, n = 1.0, 2.0, 10
    sigma = sigma_for_nats(nats, n, mu)
    rng = np.random.default_rng(0)
    s = mu + sigma * rng.standard_normal((20000, n))  # Y = 1
    assert signal_llr(s, mu, sigma).sum(axis=1).mean() == pytest.approx(nats, rel=0.03)


# ------------------------------------------- correlated research: exact posterior


@pytest.mark.parametrize("rho", [0.0, 0.3, 0.8, 1.0])
@pytest.mark.parametrize("k", [1, 2, 5])
def test_group_posterior_matches_brute_force_multivariate_gaussian(rho: float, k: int) -> None:
    """The closed form 2·mu·Σs/(k·tau² + sigma_e²) equals the full multivariate Gaussian likelihood ratio."""
    mu, v = 1.0, 4.0
    noise = ResearchNoise(mu=mu, common_var=rho * v, idio_var=(1 - rho) * v)
    cov = noise.common_var * np.ones((k, k)) + noise.idio_var * np.eye(k)
    rng = np.random.default_rng(k)
    for _ in range(5):
        s = rng.normal(0.3, 2.0, size=k)
        if rho == 1.0:
            s[:] = s[0]  # with one shared signal, all observations are identical (cov is singular)
            brute = signal_llr(s[0], mu, math.sqrt(v))
        else:
            brute = multivariate_normal.logpdf(s, mu * np.ones(k), cov) - multivariate_normal.logpdf(s, -mu * np.ones(k), cov)
        assert noise.group_coefficient(k) * s.sum() == pytest.approx(brute, rel=1e-9, abs=1e-9)


def test_rho_is_reproduced_and_pooled_information_is_fixed(base_config: SimConfig) -> None:
    """Configured rho is the signals' correlation, and full-participation information does not depend on rho."""
    n = base_config.agents.forecasters.count
    pooled = []
    for rho in (0.0, 0.4, 1.0):
        noise = research_noise(_with_rho(base_config, rho))
        assert noise.rho == pytest.approx(rho)
        pooled.append(noise.common_var + noise.idio_var / n)
    assert pooled == pytest.approx([pooled[0]] * 3)


def test_rho_zero_is_sum_of_individual_llrs(base_config: SimConfig) -> None:
    tape = _tape(_with_rho(base_config, 0.0), 2)
    np.testing.assert_allclose(tape.group_private_llr([0, 3, 7]), tape.own_private_llr[[0, 3, 7]].sum(axis=0))


def test_rho_one_means_one_researcher_knows_everything(base_config: SimConfig) -> None:
    tape = _tape(_with_rho(base_config, 1.0), 2)
    np.testing.assert_allclose(tape.private_values[0], tape.private_values[4])
    np.testing.assert_allclose(p_star_avail(tape, [4]), p_star_full(tape))


def test_empirical_correlation_matches_rho(base_config: SimConfig) -> None:
    cfg = _with_rho(base_config, 0.6)
    a, b = [], []
    for seed in range(400):
        tape = _tape(cfg, seed)
        events = tape.private_values[0] != 0
        sign = 1 if tape.y == 1 else -1
        a.extend(tape.private_values[0][events] - sign * cfg.information.mu)
        b.extend(tape.private_values[1][events] - sign * cfg.information.mu)
    # ticks with two events break the per-event structure slightly; they are rare at rate 0.05
    assert np.corrcoef(a, b)[0, 1] == pytest.approx(0.6, abs=0.05)


def _calibration_gaps(cfg: SimConfig, researchers: list[int], posterior, n_seeds: int) -> list[tuple]:
    preds, ys = [], []
    for seed in range(n_seeds):
        tape = _tape(cfg, seed)
        p = posterior(tape, researchers)
        preds.extend(p[[20, 60, 100, 150]])
        ys.extend([tape.y] * 4)
    preds_arr, y_arr = np.array(preds), np.array(ys)
    gaps = []
    for lo, hi in zip(np.linspace(0, 1, 11)[:-1], np.linspace(0, 1, 11)[1:]):
        mask = (preds_arr >= lo) & (preds_arr < hi)
        if mask.sum() >= 200:
            mean_pred = preds_arr[mask].mean()
            se = math.sqrt(mean_pred * (1 - mean_pred) / mask.sum())
            gaps.append((lo, y_arr[mask].mean(), mean_pred, se))
    return gaps


@pytest.mark.parametrize("rho", [0.0, 0.6])
def test_p_star_avail_is_calibrated_monte_carlo(base_config: SimConfig, rho: float) -> None:
    """When p*_avail says 70%, Y=1 about 70% of the time, also with correlated research and partial participation."""
    for lo, freq, mean_pred, se in _calibration_gaps(_with_rho(base_config, rho), [0, 1, 2], p_star_avail, 3000):
        assert abs(freq - mean_pred) < 4 * se + 0.02, (rho, lo, freq, mean_pred)


def test_summing_llrs_as_if_independent_is_overconfident(base_config: SimConfig) -> None:
    """Negative control: ignoring the correlation gives worse (overconfident) probabilities than the exact posterior."""
    cfg = _with_rho(base_config, 0.6)
    group = list(range(10))

    def naive(tape, researchers):
        return expit(tape.prior_logodds + np.cumsum(tape.public_llr + tape.own_private_llr[researchers].sum(axis=0)))

    exact_loss, naive_loss = [], []
    for seed in range(1500):
        tape = _tape(cfg, seed)
        for posterior, losses in ((p_star_avail, exact_loss), (naive, naive_loss)):
            p = np.clip(posterior(tape, group)[[60, 150]], 1e-12, 1 - 1e-12)
            losses.append(-np.mean(np.log(p if tape.y == 1 else 1 - p)))
    diff = np.array(naive_loss) - np.array(exact_loss)
    assert diff.mean() > 4 * diff.std(ddof=1) / math.sqrt(len(diff))


# ---------------------------------------------------------- budget and limits


def test_tape_information_matches_config(base_config: SimConfig) -> None:
    """Average total LLR at close under full participation, signed by Y, equals the configured nats."""
    info = base_config.information
    for rho in (0.0, 0.7):
        cfg = _with_rho(base_config, rho)
        totals = []
        for seed in range(1500):
            tape = _tape(cfg, seed)
            sign = 1 if tape.y == 1 else -1
            totals.append(sign * (tape.public_llr.sum() + tape.group_private_llr(range(10)).sum()))
        expected = info.public.expected_nats + sum(s.nats for s in info.shocks) + info.private.pooled_nats
        se = np.std(totals) / math.sqrt(len(totals))
        assert abs(np.mean(totals) - expected) < 4 * se, rho


def test_p_star_avail_limits(base_config: SimConfig) -> None:
    tape = _tape(_with_rho(base_config, 0.5), 5)
    n = tape.private_values.shape[0]
    np.testing.assert_allclose(p_star_avail(tape, range(n)), p_star_full(tape))
    public_only = expit(tape.prior_logodds + np.cumsum(tape.public_llr))
    np.testing.assert_allclose(p_star_avail(tape, []), public_only)


def test_tape_is_deterministic(base_config: SimConfig) -> None:
    a, b = _tape(base_config, 3), _tape(base_config, 3)
    assert a.y == b.y
    np.testing.assert_array_equal(a.public_llr, b.public_llr)
    np.testing.assert_array_equal(a.private_values, b.private_values)


def test_adding_forecasters_keeps_existing_draws(base_config: SimConfig) -> None:
    """Common random numbers: forecaster 0's draws do not depend on how many forecasters exist.

    pooled_nats is scaled with the count so the per-forecaster noise variance is equal in both configs.
    """
    cfg = _with_rho(base_config, 0.0)
    small = replace_in(replace_in(cfg, "agents.forecasters.count", 3), "information.private.pooled_nats",
                       cfg.information.private.pooled_nats * 3 / cfg.agents.forecasters.count)
    a, b = _tape(small, 9), _tape(cfg, 9)
    np.testing.assert_allclose(a.private_values[0], b.private_values[0])
    np.testing.assert_array_equal(a.public_llr, b.public_llr)
