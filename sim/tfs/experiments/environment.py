"""Measurements of the environment that the order-splitting game needs (DECISIONS D-053).

The forecaster's internal model (tfs.search.order_splitting) needs numbers describing the
market it trades in. They are measured here on *baseline* runs: the no-predator PUBLIC
baseline for κ, and the reference-predator baseline for the predator's beliefs. Never on
E4 runs, so no E4 outcome can influence the model. The measurement is deterministic.

- **κ (competitor push):** the share of a forecaster's remaining gap (belief − price, in
  log-odds) that *other* traders close in one block. For forecaster 0, at every tick
  where its gap is at least `min_gap` **and it sent an order** (it still had a Kelly
  shortfall, which is the only situation the game models):

      κ_t = sign(g_t) · (price move in block t − forecaster 0's own impact) / |g_t|

  Blocks within `news_window` ticks after public news are skipped: there the price
  moves because of news, not because of the private gap. κ is the median.

  Without the "sent an order" condition the median is 0: most ticks with a gap are
  equilibrium ticks where every researcher has reached its Kelly target and nobody trades.
  That version is reported too (`kappa_all_gap_ticks`), but it answers a different question.
- **Predator beliefs** (used only if the owner chooses the measured-predator MIN model):
  the reference predator's P(informed) about forecasters at the end of a season, its
  E[drift | informed], and the share of forecaster orders that were front-run.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

from tfs.agents.predator import PredatorMemory
from tfs.core.config import SimConfig
from tfs.core.information import generate_tape
from tfs.core.rng import RngFactory
from tfs.core.types import Venue
from tfs.market.lmsr import logit
from tfs.simulation import (BlockTrace, ResearchMemory, decide_research, draw_forecaster_traits, run_market,
                            run_season)

FORECASTER = "forecaster_0"


@dataclass(frozen=True)
class KappaMeasurement:
    kappa: float  # the median over ticks where forecaster 0 traded: the value the game uses
    mean: float
    q25: float
    q75: float
    n_ticks: int
    seeds: int
    kappa_all_gap_ticks: float  # median without the "sent an order" condition (reported, not used)


def forecaster_belief_path(cfg: SimConfig, seed: int, market: int, index: int = 0) -> np.ndarray:
    """Forecaster `index`'s own-signals belief (log-odds) at each tick's decision, rebuilt from the tape.

    The tape comes from named random streams, so regenerating it reproduces the run's signals exactly.
    """
    tape = generate_tape(cfg, RngFactory(seed), market)
    latency = cfg.agents.forecasters.public_latency
    public_seen = np.concatenate([np.zeros(latency), tape.public_llr[:len(tape.public_llr) - latency]])
    return tape.prior_logodds + np.cumsum(tape.own_private_llr[index]) + np.cumsum(public_seen)


def _own_impact(block: BlockTrace) -> float:
    """Forecaster 0's own price impact in this block, in log-odds (LMSR impacts add up)."""
    return sum(logit(r.price_after) - logit(r.price_before) for r in block.receipts
               if r.ok and r.trade.agent_id == FORECASTER and r.trade.venue is Venue.MAIN)


def _sent_order(block: BlockTrace) -> bool:
    return any(getattr(p.tx, "agent_id", None) == FORECASTER for p in block.pending)


def kappa_samples(cfg: SimConfig, seed: int, market: int, min_gap: float, news_window: int,
                  only_trading: bool = True) -> list[float]:
    trace: list[BlockTrace] = []
    run_season(cfg, seed, trace_market=market, trace=trace)
    belief = forecaster_belief_path(cfg, seed, market)
    news = generate_tape(cfg, RngFactory(seed), market).public_llr != 0.0
    samples = []
    for block in trace:
        t = block.tick
        if news[max(0, t - news_window):t + 1].any():
            continue
        gap = belief[t] - logit(block.price_before)
        if abs(gap) < min_gap or (only_trading and not _sent_order(block)):
            continue
        others = logit(block.price_after) - logit(block.price_before) - _own_impact(block)
        samples.append(float(np.sign(gap) * others / abs(gap)))
    return samples


def measure_kappa(cfg: SimConfig, seeds: range, first_market: int, min_gap: float = 0.1,
                  news_window: int = 5) -> KappaMeasurement:
    """One traced market per seed, spread over the scored markets (first_market .. n_markets − 1)."""
    span = cfg.season.n_markets - first_market
    trading: list[float] = []
    every: list[float] = []
    for seed in seeds:
        market = first_market + seed % span
        trading += kappa_samples(cfg, seed, market, min_gap, news_window)
        every += kappa_samples(cfg, seed, market, min_gap, news_window, only_trading=False)
    xs = np.array(trading)
    return KappaMeasurement(float(np.median(xs)), float(xs.mean()), float(np.quantile(xs, 0.25)),
                            float(np.quantile(xs, 0.75)), len(xs), len(seeds), float(np.median(every)))


@dataclass(frozen=True)
class PredatorMeasurement:
    p_informed_mean: float  # the predator's P(informed) about forecasters at season end
    drift_mean: float  # its E[drift | informed], log-odds over its horizon
    frontrun_share: float  # front-runs per forecaster order, scored markets
    seeds: int


def measure_predator(cfg: SimConfig, seeds: range, first_market: int) -> PredatorMeasurement:
    """Run reference-predator seasons and read the predator's own memory (cfg must have one predator)."""
    p_inf, drift, frontruns, orders = [], [], 0, 0
    for seed in seeds:
        rngs = RngFactory(seed)
        traits = draw_forecaster_traits(cfg, rngs)
        research = ResearchMemory(ema=[None] * len(traits), alpha=cfg.agents.forecasters.research.ema_alpha)
        memories = [PredatorMemory()]
        for market in range(cfg.season.n_markets):  # the same loop as run_season, keeping the memory
            researchers = decide_research(cfg, traits, research, rngs, market)
            record = run_market(cfg, rngs, market, traits, researchers, memories)
            for index, gross in record.forecaster_pnl().items():
                research.update(index, gross)
            if market >= first_market:
                frontruns += record.frontruns
                orders += record.attempts_by_kind.get("forecaster", 0)
        p_inf += [b.p_informed for a, b in memories[0].beliefs.items() if a.startswith("forecaster")]
        if memories[0].drift_ema is not None:
            drift.append(memories[0].drift_ema)
    return PredatorMeasurement(float(np.mean(p_inf)), float(np.mean(drift)), frontruns / orders, len(seeds))


def as_dict(*measurements: object) -> dict:
    return {type(m).__name__: asdict(m) for m in measurements}  # type: ignore[call-overload]
