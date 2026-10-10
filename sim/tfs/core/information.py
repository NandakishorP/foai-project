"""The information model (SPEC §2): hidden outcome, Gaussian signals, ideal prices.

Every market has a hidden binary outcome Y. Information about Y arrives as
Gaussian signals centred on +mu if Y=1 and −mu if Y=0.

Public news and shocks are independent signals s ~ N(±mu, sigma²). A Bayesian
adds each one's log-likelihood ratio LLR(s) = 2·mu·s / sigma² to its log-odds.

**False breaking news** (Q1, DECISIONS D-053). A shock is false with a probability
q_false that everyone knows. A false shock's signal points the wrong way:
s ~ N(∓mu, sigma²). A Bayesian who cannot yet tell true from false uses the mixture

    LLR_mix(s) = log[(1−q)·e^L + q] − log[(1−q) + q·e^L],   L = 2·mu·s / sigma².

It discounts a shock, never reverses it. `correction_delay` ticks later the shock's
status is published. From then on the exact LLR applies: +L if it was true, −L if it
was false. So the tape adds (exact − LLR_mix) at the correction tick. Both ideal
prices use the same tape, so they remain exact posteriors, and the decomposition (D-001)
still holds when shocks are drawn with probability q_false. Scenarios that *force* a
shock to be false condition on a rare event, so the decomposition is not claimed for them.

Research signals are correlated across forecasters (DECISIONS D-024). At each
research event, every potential forecaster i receives

    s_i = ±mu + u + e_i,   u ~ N(0, tau²) common to all,  e_i ~ N(0, sigma_e²) idiosyncratic.

Given Y, two forecasters' signals have correlation rho = tau² / (tau² + sigma_e²):
rho = 0 is independent research, rho = 1 is one shared research signal (the
textbook Grossman–Stiglitz setting).

**Exact posterior for a group S of k researchers.** The vector s_S is
N(±mu·1, Sigma) with Sigma = tau²·11ᵀ + sigma_e²·I. The log-likelihood ratio is
2·mu·1ᵀ Sigma⁻¹ s_S, and by the Sherman–Morrison formula
1ᵀ Sigma⁻¹ = 1ᵀ / (k·tau² + sigma_e²). Hence

    LLR_S = 2·mu · Σ_{i∈S} s_i / (k·tau² + sigma_e²) = 2·mu · mean(s_S) / (tau² + sigma_e²/k).

The group's mean signal is sufficient. Its noise variance tau² + sigma_e²/k
shrinks with k only down to the common floor tau², so adding researchers stops
adding information as rho → 1. Summing the individual LLRs instead would
divide by k·(tau² + sigma_e²) per signal and over-count the common noise
whenever rho > 0. A single forecaster (k = 1) uses 2·mu·s_i / (tau² + sigma_e²).

All signals of a market are generated up front into a `SignalTape`, including
the research signals of *every* potential forecaster, researching or not. Runs
that differ only in who researches therefore see the same information.
- p*_full : posterior from public news plus all potential research (everyone researches).
- p*_avail: posterior from public news plus the research of those who actually researched.

Information strength is configured in "nats" (expected total LLR per market).
With Y=1 a signal with noise variance V has expected LLR 2·mu² / V, so
`expected_signals` such signals carry nats = expected_signals · 2·mu² / V.
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


def mixture_llr(llr: float, q_false: float) -> float:
    """LLR of a shock that is false (points the wrong way) with probability q_false; see the module docstring."""
    if q_false == 0.0:
        return llr  # exactly the ordinary LLR: no floating-point change to earlier results
    keep, flip = math.log1p(-q_false), math.log(q_false)
    return float(np.logaddexp(keep + llr, flip) - np.logaddexp(keep, flip + llr))


def signal_llr(s: np.ndarray | float, mu: float, sigma: float) -> np.ndarray | float:
    """Log-likelihood ratio of one independent signal: log[N(s; +mu, sigma) / N(s; -mu, sigma)] = 2 mu s / sigma^2."""
    return 2.0 * mu * s / sigma**2


def sigma_for_nats(nats: float, expected_signals: float, mu: float) -> float:
    """Signal noise sigma such that `expected_signals` independent signals carry `nats` expected LLR in total."""
    if nats <= 0 or expected_signals <= 0:
        raise ValueError("nats and expected_signals must be positive")
    return math.sqrt(2.0 * mu**2 * expected_signals / nats)


@dataclass(frozen=True)
class ResearchNoise:
    """Noise structure of research signals: s_i = ±mu + u + e_i."""

    mu: float
    common_var: float  # tau²: variance of the component u shared by all forecasters at an event
    idio_var: float  # sigma_e²: variance of each forecaster's own noise e_i

    @property
    def rho(self) -> float:
        return self.common_var / (self.common_var + self.idio_var)

    def group_coefficient(self, k: int) -> float:
        """LLR per unit of summed signal for a group of k researchers: 2·mu / (k·tau² + sigma_e²)."""
        return 2.0 * self.mu / (k * self.common_var + self.idio_var)


def research_noise(cfg: SimConfig) -> ResearchNoise:
    """Derive tau² and sigma_e² from the configured pooled information and rho.

    The pooled research of all N potential forecasters has, per event, noise variance
    V_pool = tau² + sigma_e²/N = v·(rho + (1 − rho)/N), with v = tau² + sigma_e² one
    forecaster's total noise. We fix V_pool so that full participation carries
    `pooled_nats` per market, whatever rho is. Sweeping rho then changes how the
    same total information is spread across forecasters, not how much exists.
    At rho = 0 each forecaster holds pooled_nats / N; at rho = 1 each holds all of it.
    """
    info = cfg.information
    priv = info.private
    n = max(cfg.agents.forecasters.count, 1)
    expected_events = priv.rate * cfg.market.ticks
    pooled_var = 2.0 * info.mu**2 * expected_events / (priv.pooled_nats * info.precision_scale)
    one_forecaster_var = pooled_var / (priv.rho + (1.0 - priv.rho) / n)
    return ResearchNoise(
        mu=info.mu, common_var=priv.rho * one_forecaster_var, idio_var=(1.0 - priv.rho) * one_forecaster_var
    )


@dataclass(frozen=True)
class ForecasterTraits:
    """Fixed characteristics of one potential forecaster for a whole season.

    Research quality is the same for all forecasters (DECISIONS D-025): with rho = 1
    every forecaster must observe the identical signal. Heterogeneity comes from
    research costs.
    """

    index: int
    cost: float | None  # research cost c_i per market (None when costs are not used)


def draw_forecaster_traits(cfg: SimConfig, rngs: RngFactory) -> list[ForecasterTraits]:
    """Draw each forecaster's research cost (SPEC §2.1 heterogeneity), lognormal around the median.

    Each forecaster has its own stream, so adding forecasters leaves existing
    costs unchanged. The draw does not depend on `cost_median`, which only rescales it.
    """
    research = cfg.agents.forecasters.research
    traits = []
    for i in range(cfg.agents.forecasters.count):
        z = rngs.stream("forecaster_traits", 0, i).standard_normal()
        cost = None if research.cost_median is None else research.cost_median * math.exp(research.cost_log_sigma * z)
        traits.append(ForecasterTraits(index=i, cost=cost))
    return traits


@dataclass(frozen=True)
class SignalTape:
    """Every signal of one market, aggregated per tick.

    Agents never read the tape directly; the simulation hands each agent only
    what it is allowed to see (its own research signals, public news after its latency).
    """

    y: int  # the hidden outcome
    prior_logodds: float
    public_llr: np.ndarray  # shape (ticks,): LLR of public news and shocks published at each tick
    private_values: np.ndarray  # shape (n_forecasters, ticks): each forecaster's raw research signals, by emission tick
    private_values_seen: np.ndarray  # same signals by the tick each forecaster receives them (= emission if no delay)
    noise: ResearchNoise
    shock_ticks: tuple[int, ...]
    shock_false: tuple[bool, ...] = ()  # was each shock false news?
    correction_ticks: tuple[int, ...] = ()  # when each shock's status was published (empty if q_false = 0)

    @property
    def ticks(self) -> int:
        return self.public_llr.shape[0]

    @property
    def own_private_llr(self) -> np.ndarray:
        """What each forecaster alone can infer from its own research, per tick it *receives* it (k = 1 posterior)."""
        return self.noise.group_coefficient(1) * self.private_values_seen

    def group_private_llr(self, researchers: Collection[int]) -> np.ndarray:
        """Exact LLR per tick of the research of a group, accounting for the shared noise."""
        if len(researchers) == 0:
            return np.zeros(self.ticks)
        summed = self.private_values[sorted(researchers)].sum(axis=0)
        return self.noise.group_coefficient(len(researchers)) * summed


def _poisson_signals_llr(
    rng: np.random.Generator, rate: float, ticks: int, sign: int, mu: float, sigma: float
) -> np.ndarray:
    """LLR per tick of a Poisson stream of independent Gaussian signals (several may land on one tick)."""
    counts = rng.poisson(rate, size=ticks)
    noise = rng.standard_normal(int(counts.sum()))
    values = sign * mu + sigma * noise
    llr_per_tick = np.zeros(ticks)
    np.add.at(llr_per_tick, np.repeat(np.arange(ticks), counts), signal_llr(values, mu, sigma))
    return llr_per_tick


def _research_values(
    cfg: SimConfig, rngs: RngFactory, market: int, sign: int, noise: ResearchNoise
) -> tuple[np.ndarray, np.ndarray]:
    """Raw research signals of every potential forecaster, summed per tick: (by emission, by arrival).

    Event times and the common component u come from shared streams. Each
    forecaster's own noise e_i comes from its own stream, so it is unaffected
    by how many other forecasters exist.

    Staggered arrival (exploratory X-3, `max_delay` > 0): each forecaster
    receives each research event 0..max_delay ticks after it is emitted, with
    the delay drawn per (event, forecaster) from the forecaster's own delay
    stream. Signals that would arrive after the market ends are never seen.
    The ideal prices keep emission times, as they do for public news latency,
    so p*_avail is unchanged and the decomposition (D-001) still holds.
    """
    ticks = cfg.market.ticks
    n = cfg.agents.forecasters.count
    counts = rngs.stream("research_events", market).poisson(cfg.information.private.rate, size=ticks)
    n_events = int(counts.sum())
    event_tick = np.repeat(np.arange(ticks), counts)
    common = math.sqrt(noise.common_var) * rngs.stream("research_common", market).standard_normal(n_events)

    max_delay = cfg.information.private.max_delay
    values = np.zeros((n, ticks))
    seen = values if max_delay == 0 else np.zeros((n, ticks))
    for i in range(n):
        own = math.sqrt(noise.idio_var) * rngs.stream("private", market, i).standard_normal(n_events)
        signals = sign * noise.mu + common + own
        np.add.at(values[i], event_tick, signals)
        if max_delay > 0:
            arrival = event_tick + rngs.stream("research_delay", market, i).integers(0, max_delay + 1, n_events)
            on_time = arrival < ticks
            np.add.at(seen[i], arrival[on_time], signals[on_time])
    return values, seen


def generate_tape(cfg: SimConfig, rngs: RngFactory, market: int) -> SignalTape:
    """Draw Y and all signals of market `market` in a season."""
    info = cfg.information
    ticks = cfg.market.ticks
    prior = cfg.market.prior

    y = int(rngs.stream("outcome", market).random() < prior)
    sign = 1 if y == 1 else -1

    public_sigma = sigma_for_nats(info.public.expected_nats * info.precision_scale, info.public.rate * ticks, info.mu)
    public_llr = _poisson_signals_llr(rngs.stream("public_news", market), info.public.rate, ticks, sign, info.mu, public_sigma)

    shock_false, corrections = [], []
    for k, shock in enumerate(info.shocks):
        shock_sigma = sigma_for_nats(shock.nats * info.precision_scale, 1.0, info.mu)
        false = _shock_is_false(shock.status, info.q_false, rngs, market, k)
        direction = -sign if false else sign
        value = direction * info.mu + shock_sigma * rngs.stream("shock", market, k).standard_normal()
        llr = float(signal_llr(value, info.mu, shock_sigma))
        public_llr[shock.tick] += mixture_llr(llr, info.q_false)
        if info.q_false > 0:  # the correction turns the mixture LLR into the exact one
            exact = -llr if false else llr
            public_llr[shock.tick + info.correction_delay] += exact - mixture_llr(llr, info.q_false)
            corrections.append(shock.tick + info.correction_delay)
        shock_false.append(false)

    noise = research_noise(cfg)
    private_values, private_values_seen = _research_values(cfg, rngs, market, sign, noise)
    return SignalTape(
        y=y,
        prior_logodds=logit(prior),
        public_llr=public_llr,
        private_values=private_values,
        private_values_seen=private_values_seen,
        noise=noise,
        shock_ticks=tuple(s.tick for s in info.shocks),
        shock_false=tuple(shock_false),
        correction_ticks=tuple(corrections),
    )


def _shock_is_false(status: str, q_false: float, rngs: RngFactory, market: int, k: int) -> bool:
    """A forced status, or a draw with probability q_false from the shock's own stream."""
    if status != "drawn":
        return status == "false"
    return q_false > 0 and bool(rngs.stream("shock_false", market, k).random() < q_false)


def ideal_logodds(tape: SignalTape, researchers: Collection[int]) -> np.ndarray:
    """Posterior log-odds at each tick using public signals + the research of `researchers`."""
    return tape.prior_logodds + np.cumsum(tape.public_llr + tape.group_private_llr(researchers))


def p_star_full(tape: SignalTape) -> np.ndarray:
    """Best price the market could ever know: everyone's research used."""
    return expit(ideal_logodds(tape, range(tape.private_values.shape[0])))


def p_star_avail(tape: SignalTape, researchers: Collection[int]) -> np.ndarray:
    """Best price given the research that was actually acquired this run."""
    return expit(ideal_logodds(tape, researchers))
