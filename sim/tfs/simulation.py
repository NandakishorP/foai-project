"""The simulation loop (SPEC §3.1): one market, and a season of markets with research decisions.

Per tick (1 tick = 1 block):
  1. the world publishes this tick's signals (already drawn into the SignalTape);
  2. each agent perceives what it may see and returns transactions;
  3. the builder orders the transactions (Phase 1: random arrival order);
  4. the engine executes the block;
  5. prices are recorded.
At the end the market resolves on the true outcome (the oracle arrives in Phase 3).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

from tfs.agents.arbitrageur import Arbitrageur
from tfs.agents.base import Agent, Observation
from tfs.agents.beliefs import make_belief
from tfs.agents.forecaster import InformedForecaster
from tfs.agents.noise import NoiseTrader
from tfs.agents.public_news import PublicNewsTrader
from tfs.agents.trend import TrendFollower
from tfs.core.config import SimConfig
from tfs.core.information import (
    ForecasterTraits,
    SignalTape,
    draw_forecaster_traits,
    generate_tape,
    p_star_avail,
    p_star_full,
)
from tfs.core.rng import RngFactory
from tfs.core.types import Receipt, Tx, Venue
from tfs.engines.fast import FastEngine


class ArrivalOrderBuilder:
    """Phase 1 builder: transactions land in a random arrival order, with no reordering for profit.

    Phase 2a replaces this with the mempool and a profit-seeking builder.
    """

    def __init__(self, rng: np.random.Generator) -> None:
        self.rng = rng

    def order(self, txs: Sequence[Tx]) -> list[Tx]:
        return [txs[i] for i in self.rng.permutation(len(txs))]


# --------------------------------------------------------------------------- #
# Building the agent population of one market
# --------------------------------------------------------------------------- #


def build_agents(
    cfg: SimConfig, rngs: RngFactory, market: int, traits: Sequence[ForecasterTraits], researchers: frozenset[int]
) -> list[Agent]:
    """Create every agent trading in this market. Non-researching forecasters do not take part (D-014)."""
    a = cfg.agents
    b = {Venue.MAIN: cfg.market.b_main, Venue.REF: cfg.market.b_ref}
    prior_logodds = float(np.log(cfg.market.prior / (1.0 - cfg.market.prior)))
    agents: list[Agent] = []

    fc = a.forecasters
    for t in traits:
        if t.index in researchers:
            agents.append(
                InformedForecaster(
                    index=t.index,
                    liquidity=b[Venue.MAIN],
                    belief=make_belief(a.belief_model, prior_logodds),
                    kelly_fraction=fc.kelly_fraction,
                    bankroll=fc.bankroll,
                    max_order=fc.max_order,
                    min_order=fc.min_order,
                    public_latency=fc.public_latency,
                )
            )

    for venue, pc in ((Venue.MAIN, a.public_main), (Venue.REF, a.public_ref)):
        for j in range(pc.count):
            agents.append(
                PublicNewsTrader(
                    agent_id=f"public_{venue.value}_{j}",
                    venue=venue,
                    liquidity=b[venue],
                    belief=make_belief(a.belief_model, prior_logodds),
                    kelly_fraction=pc.kelly_fraction,
                    bankroll=pc.bankroll,
                    max_order=pc.max_order,
                    min_order=pc.min_order,
                    delay=pc.delay,
                )
            )

    for venue, nc in ((Venue.MAIN, a.noise_main), (Venue.REF, a.noise_ref)):
        for j in range(nc.count):
            agents.append(
                NoiseTrader(
                    agent_id=f"noise_{venue.value}_{j}",
                    venue=venue,
                    rate=nc.rate,
                    mean_size=nc.mean_size,
                    bankroll=nc.bankroll,
                    rng=rngs.stream(f"noise_{venue.value}", market, j),
                )
            )

    for j in range(a.arbitrageurs.count):
        ac = a.arbitrageurs
        agents.append(Arbitrageur(f"arb_{j}", b, ac.capital, ac.min_profit, ac.slippage))

    for j in range(a.trend.count):
        tc = a.trend
        agents.append(
            TrendFollower(
                f"trend_{j}", tc.fast_span, tc.slow_span, tc.threshold, tc.order_size, tc.max_position, tc.bankroll
            )
        )
    return agents


# --------------------------------------------------------------------------- #
# One market
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class MarketRecord:
    """Everything measured in one market."""

    market: int
    y: int
    researchers: frozenset[int]
    price_main: np.ndarray  # main-market YES price after each block
    price_ref: np.ndarray
    p_full: np.ndarray
    p_avail: np.ndarray
    p_public: np.ndarray  # posterior from public news alone: what the market knows if research is ignored
    shock_ticks: tuple[int, ...]
    pnl: dict[str, float]  # agent_id -> final cash minus starting cash (gross of research cost)
    kinds: dict[str, str]  # agent_id -> agent kind
    mm_pnl: dict[Venue, float]
    executed: int  # trades that filled
    reverted: int  # trades that reverted

    def forecaster_pnl(self) -> dict[int, float]:
        """Gross trading PnL of each researching forecaster, by forecaster index."""
        return {int(aid.rsplit("_", 1)[1]): v for aid, v in self.pnl.items() if self.kinds[aid] == "forecaster"}


def _visible_public_llr(tape: SignalTape, tick: int, latency: int | None) -> float:
    """Public LLR that becomes visible at `tick` to an agent with the given latency."""
    if latency is None or tick - latency < 0:
        return 0.0
    return float(tape.public_llr[tick - latency])


def run_market(
    cfg: SimConfig,
    rngs: RngFactory,
    market: int,
    traits: Sequence[ForecasterTraits],
    researchers: frozenset[int],
) -> MarketRecord:
    tape = generate_tape(cfg, list(traits), rngs, market)
    agents = build_agents(cfg, rngs, market, traits, researchers)
    engine = FastEngine(
        {Venue.MAIN: cfg.market.b_main, Venue.REF: cfg.market.b_ref},
        {agent.agent_id: agent.bankroll for agent in agents},
    )
    builder = ArrivalOrderBuilder(rngs.stream("builder", market))

    ticks = cfg.market.ticks
    price_main, price_ref = np.empty(ticks), np.empty(ticks)
    pending_receipts: dict[str, list[Receipt]] = defaultdict(list)
    executed = reverted = 0

    for tick in range(ticks):
        prices = engine.prices()
        balances = engine.balances()
        txs: list[Tx] = []
        for agent in agents:
            private = 0.0 if agent.private_source is None else float(tape.private_llr[agent.private_source, tick])
            agent.perceive(
                Observation(
                    tick=tick,
                    prices=prices,
                    public_llr=_visible_public_llr(tape, tick, agent.public_latency),
                    private_llr=private,
                    account=balances[agent.agent_id],
                    receipts=tuple(pending_receipts.pop(agent.agent_id, ())),
                )
            )
            txs.extend(agent.act())

        for receipt in engine.build_block(builder.order(txs)):
            pending_receipts[receipt.trade.agent_id].append(receipt)
            executed += receipt.ok
            reverted += not receipt.ok

        after = engine.prices()
        price_main[tick], price_ref[tick] = after[Venue.MAIN], after[Venue.REF]

    engine.resolve(tape.y)
    final = engine.balances()
    return MarketRecord(
        market=market,
        y=tape.y,
        researchers=researchers,
        price_main=price_main,
        price_ref=price_ref,
        p_full=p_star_full(tape),
        p_avail=p_star_avail(tape, researchers),
        p_public=p_star_avail(tape, []),
        shock_ticks=tape.shock_ticks,
        pnl={a.agent_id: final[a.agent_id].cash - a.bankroll for a in agents},
        kinds={a.agent_id: a.kind for a in agents},
        mm_pnl=engine.market_maker_pnl(),
        executed=executed,
        reverted=reverted,
    )


# --------------------------------------------------------------------------- #
# A season: endogenous research decisions across markets (SPEC §2.1)
# --------------------------------------------------------------------------- #


@dataclass
class ResearchMemory:
    """Each forecaster's running estimate of its gross profit per researched market.

    `None` means "no experience yet". A forecaster with no experience researches
    (optimistic initialisation, DECISIONS D-020), so participation in a season's
    first market is fixed: everyone researches.
    """

    ema: list[float | None]
    alpha: float

    def update(self, index: int, gross_profit: float) -> None:
        old = self.ema[index]
        self.ema[index] = gross_profit if old is None else old + self.alpha * (gross_profit - old)


def decide_research(
    cfg: SimConfig, traits: Sequence[ForecasterTraits], memory: ResearchMemory, rngs: RngFactory, market: int
) -> frozenset[int]:
    """Who researches in this market: research iff EMA(profit) > cost, or with probability epsilon anyway."""
    research = cfg.agents.forecasters.research
    if research.mode == "always":
        return frozenset(t.index for t in traits)
    chosen = set()
    for t in traits:
        # Draw the exploration coin every time, so the stream does not depend on past decisions.
        explore = rngs.stream("research_explore", market, t.index).random() < research.explore_prob
        estimate = memory.ema[t.index]
        assert t.cost is not None  # guaranteed by config validation in endogenous mode
        if estimate is None or estimate > t.cost or explore:
            chosen.add(t.index)
    return frozenset(chosen)


@dataclass
class SeasonRecord:
    seed: int
    traits: list[ForecasterTraits]
    markets: list[MarketRecord] = field(default_factory=list)

    def participation(self) -> list[float]:
        n = len(self.traits)
        return [len(m.researchers) / n if n else 0.0 for m in self.markets]


def run_season(cfg: SimConfig, seed: int) -> SeasonRecord:
    rngs = RngFactory(seed)
    traits = draw_forecaster_traits(cfg, rngs)
    memory = ResearchMemory(ema=[None] * len(traits), alpha=cfg.agents.forecasters.research.ema_alpha)
    season = SeasonRecord(seed=seed, traits=traits)
    for market in range(cfg.season.n_markets):
        researchers = decide_research(cfg, traits, memory, rngs, market)
        record = run_market(cfg, rngs, market, traits, researchers)
        for index, gross in record.forecaster_pnl().items():
            memory.update(index, gross)
        season.markets.append(record)
    return season
