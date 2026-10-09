"""The information model (SPEC §2): hidden outcome, Gaussian signals, ideal prices.

Every market has a hidden binary outcome Y. Information about Y arrives as
Gaussian signals s ~ N(+mu, sigma^2) if Y=1 and N(-mu, sigma^2) if Y=0. A
Bayesian adds each signal's log-likelihood ratio LLR(s) = 2 mu s / sigma^2 to
its log-odds.

All signals of a market are generated up front into a `SignalTape`. That
includes the private signals of *every* potential forecaster, whether or not it
researches. Runs that differ only in who researches therefore see the same
information. Two ideal prices are then computed from the tape:

- p*_full : posterior from all potential signals (as if everyone researched).
- p*_avail: posterior from public signals + private signals of the forecasters
  who actually researched.

Information strength is configured in "nats" (expected total LLR contributed per
market) and converted to sigma. The derivation: with Y=1, one signal's expected
LLR is E[2 mu s / sigma^2] = 2 mu^2 / sigma^2. A source emitting on average
`rate * ticks` signals therefore contributes nats = rate * ticks * 2 mu^2 / sigma^2.
By symmetry the same magnitude, negated, holds for Y=0.
"""

from __future__ import annotations

import math
from collections.abc import Collection
from dataclasses import dataclass

import numpy as np
from scipy.special import expit

from tfs.core.config import SimConfig
from tfs.core.rng import RngFactory


def logit(p: float) -> float:
    return math.log(p / (1.0 - p))


def signal_llr(s: np.ndarray | float, mu: float, sigma: float) -> np.ndarray | float:
    """Log-likelihood ratio log[N(s; +mu, sigma) / N(s; -mu, sigma)] = 2 mu s / sigma^2."""
    return 2.0 * mu * s / sigma**2


def sigma_for_nats(nats: float, expected_signals: float, mu: float) -> float:
    """Signal noise sigma such that `expected_signals` signals carry `nats` expected LLR in total."""
    if nats <= 0 or expected_signals <= 0:
        raise ValueError("nats and expected_signals must be positive")
    return math.sqrt(2.0 * mu**2 * expected_signals / nats)


@dataclass(frozen=True)
class ForecasterTraits:
    """Fixed characteristics of one potential forecaster for a whole season."""

    index: int
    nats: float  # expected private information per researched market
    sigma: float  # noise of each private signal
    cost: float | None  # research cost c_i per market (None when costs are not used)


def draw_forecaster_traits(cfg: SimConfig, rngs: RngFactory) -> list[ForecasterTraits]:
    """Draw each forecaster's information quality and research cost (SPEC §2.1 heterogeneity).

    Each forecaster has its own stream, so adding forecasters leaves the
    existing ones unchanged. The draws themselves do not depend on
    `precision_scale` or `cost_median`, which only rescale them. Sweeping those
    parameters therefore compares the same population.
    """
    info = cfg.information
    priv = info.private
    research = cfg.agents.forecasters.research
    expected_signals = priv.rate * cfg.market.ticks
    traits = []
    for i in range(cfg.agents.forecasters.count):
        rng = rngs.stream("forecaster_traits", 0, i)
        u = rng.random()
        z = rng.standard_normal()
        nats = (priv.nats_min + u * (priv.nats_max - priv.nats_min)) * info.precision_scale
        cost = None if research.cost_median is None else research.cost_median * math.exp(research.cost_log_sigma * z)
        traits.append(
            ForecasterTraits(index=i, nats=nats, sigma=sigma_for_nats(nats, expected_signals, info.mu), cost=cost)
        )
    return traits


@dataclass(frozen=True)
class SignalTape:
    """Every signal of one market, aggregated per tick as log-likelihood ratios.

    Agents never read the tape directly; the simulation hands each agent only
    what it is allowed to see (its own private signals, public news after its
    latency).
    """

    y: int  # the hidden outcome
    prior_logodds: float
    public_llr: np.ndarray  # shape (ticks,): LLR of public news and shocks published at each tick
    private_llr: np.ndarray  # shape (n_forecasters, ticks): each forecaster's private LLR per tick
    shock_ticks: tuple[int, ...]

    @property
    def ticks(self) -> int:
        return self.public_llr.shape[0]


def _poisson_signals_llr(
    rng: np.random.Generator, rate: float, ticks: int, sign: int, mu: float, sigma: float
) -> np.ndarray:
    """LLR per tick of a Poisson stream of Gaussian signals (several may land on one tick)."""
    counts = rng.poisson(rate, size=ticks)
    noise = rng.standard_normal(int(counts.sum()))
    values = sign * mu + sigma * noise
    llr_per_tick = np.zeros(ticks)
    np.add.at(llr_per_tick, np.repeat(np.arange(ticks), counts), signal_llr(values, mu, sigma))
    return llr_per_tick


def generate_tape(cfg: SimConfig, traits: list[ForecasterTraits], rngs: RngFactory, market: int) -> SignalTape:
    """Draw Y and all signals of market `market` in a season."""
    info = cfg.information
    ticks = cfg.market.ticks
    prior = cfg.market.prior

    y = int(rngs.stream("outcome", market).random() < prior)
    sign = 1 if y == 1 else -1

    public_sigma = sigma_for_nats(info.public.expected_nats * info.precision_scale, info.public.rate * ticks, info.mu)
    public_llr = _poisson_signals_llr(rngs.stream("public_news", market), info.public.rate, ticks, sign, info.mu, public_sigma)

    for k, shock in enumerate(info.shocks):
        shock_sigma = sigma_for_nats(shock.nats * info.precision_scale, 1.0, info.mu)
        value = sign * info.mu + shock_sigma * rngs.stream("shock", market, k).standard_normal()
        public_llr[shock.tick] += signal_llr(value, info.mu, shock_sigma)

    private_llr = np.zeros((len(traits), ticks))
    for t in traits:
        private_llr[t.index] = _poisson_signals_llr(
            rngs.stream("private", market, t.index), info.private.rate, ticks, sign, info.mu, t.sigma
        )

    return SignalTape(
        y=y,
        prior_logodds=logit(prior),
        public_llr=public_llr,
        private_llr=private_llr,
        shock_ticks=tuple(s.tick for s in info.shocks),
    )


def ideal_logodds(tape: SignalTape, researchers: Collection[int]) -> np.ndarray:
    """Posterior log-odds at each tick using public signals + private signals of `researchers`."""
    increments = tape.public_llr.copy()
    if len(researchers) > 0:
        increments += tape.private_llr[sorted(researchers)].sum(axis=0)
    return tape.prior_logodds + np.cumsum(increments)


def p_star_full(tape: SignalTape) -> np.ndarray:
    """Best price the market could ever know: every potential signal used."""
    return expit(ideal_logodds(tape, range(tape.private_llr.shape[0])))


def p_star_avail(tape: SignalTape, researchers: Collection[int]) -> np.ndarray:
    """Best price given the information that was actually acquired this run."""
    return expit(ideal_logodds(tape, researchers))
