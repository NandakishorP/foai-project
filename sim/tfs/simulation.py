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
from tfs.agents.attackers import FreeOptionTrader, NonRevealGriefer, SpamCommitter
from tfs.agents.metadata_predator import MetadataPredator
from tfs.agents.noise import NoiseTrader
from tfs.agents.predator import Predator, PredatorMemory, exposure_direction
from tfs.agents.public_news import PublicNewsTrader
from tfs.agents.slicing import make_slice_rule
from tfs.agents.trend import TrendFollower
from tfs.agents.whale import WhaleManipulator, yes_target as whale_yes_target
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
from tfs.core.types import Bundle, Receipt, Side, Trade, Tx, Venue
from tfs.engines.fast import SLASHED_ID, FastEngine
from tfs.mempool.batch_desk import BatchDesk
from tfs.mempool.builder import BlockPlan, FeeBuilder, FrontRunRequest
from tfs.mempool.mempool import Mempool, MempoolPolicy, PendingTx
from tfs.search.order_splitting import OrderSplittingGame, SplittingPolicy, split_params


# --------------------------------------------------------------------------- #
# Building the agent population of one market
# --------------------------------------------------------------------------- #


def build_agents(
    cfg: SimConfig,
    rngs: RngFactory,
    market: int,
    traits: Sequence[ForecasterTraits],
    researchers: frozenset[int],
    predator_memories: Sequence[PredatorMemory] = (),
    splitting: SplittingPolicy | None = None,
    outcome: int | None = None,
) -> list[Agent]:
    """Create every agent trading in this market. Non-researching forecasters do not take part (D-014).

    Predators get the memory they carry across the season (D-033 amendment 4). Forecasters
    using the expectiminimax slice rule share the season's `splitting` policy (solved game states).
    """
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
                    bankroll=fc.capital_ratio * cfg.market.b_main,
                    max_order=fc.max_order,
                    min_order=fc.min_order,
                    public_latency=fc.public_latency,
                    slice_rule=make_slice_rule(fc.execution, fc.max_order, t.index,
                                               rngs.stream("slice_random", market, t.index), splitting),
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

    depeg = cfg.market.depeg
    for venue, nc in ((Venue.MAIN, a.noise_main), (Venue.REF, a.noise_ref)):
        for j in range(nc.count):
            trader = NoiseTrader(
                agent_id=f"noise_{venue.value}_{j}",
                venue=venue,
                rate=nc.rate,
                mean_size=nc.mean_size,
                bankroll=nc.bankroll,
                rng=rngs.stream(f"noise_{venue.value}", market, j),
            )
            # Depeg (S-D): each main-market noise trader sits the window out with the scenario's probability.
            if venue is Venue.MAIN and depeg.discount > 0:
                if rngs.stream("depeg_withdraw", market, j).random() < depeg.noise_withdrawal:
                    trader.away = range(depeg.start, depeg.end)
            agents.append(trader)

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

    wc = a.whale
    for j in range(wc.count):
        target = whale_yes_target(wc, outcome if outcome is not None else 1)
        agents.append(WhaleManipulator(f"whale_{j}", b[Venue.MAIN], wc.budget, target, wc.start, wc.end, wc.budget))

    batched = MempoolPolicy(cfg.mempool.policy).batched
    memories = list(predator_memories) or [PredatorMemory() for _ in range(a.predators.count)]
    if len(memories) != a.predators.count:
        raise ValueError("one memory per predator is required")
    for j, memory in enumerate(memories):
        if batched:  # under sealed batches the predator can only copy-trade from metadata (H3a)
            proving = cfg.mempool.proving_delay if cfg.mempool.policy == "zk_batch" else 0
            agents.append(MetadataPredator(f"predator_{j}", b[Venue.MAIN], a.predators, memory, cfg.market.ticks,
                                           cfg.mempool.batch_interval, proving))
        else:
            agents.append(Predator(f"predator_{j}", b[Venue.MAIN], a.predators, memory, cfg.market.ticks,
                                   cfg.mempool.base_fee))

    at = a.attackers
    if (at.non_reveal or at.free_option or at.spam) and not batched:
        raise ValueError("attackers only exist under sealed-batch policies")
    K = cfg.mempool.batch_interval
    for j in range(at.non_reveal):
        agents.append(NonRevealGriefer(f"griefer_{j}", at.size, at.bankroll, K, rngs.stream("griefer", market, j)))
    for j in range(at.free_option):
        for side in (Side.YES, Side.NO):
            agents.append(FreeOptionTrader(f"freeopt_{j}_{side.value}", f"freeopt_{j}", side, at.size, at.bankroll, K))
    for j in range(at.spam):
        agents.append(SpamCommitter(f"spam_{j}", at.size * 10, at.bankroll, K))  # insolvent: 10x what one tier covers
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
    bankrolls: dict[str, float]  # agent_id -> starting cash (lets a traced market be replayed on another engine)
    kinds: dict[str, str]  # agent_id -> agent kind
    mm_pnl: dict[Venue, float]
    executed: int  # trades that filled
    reverted: int  # trades that reverted
    builder_revenue: float  # fees and tips collected by the builder
    attempts_by_kind: dict[str, int]  # trades sent, by agent kind
    reverts_by_kind: dict[str, int]  # of which reverted
    frontruns: int  # predator front-runs that filled
    victim_reverts: int  # victims that reverted after being front-run
    requested_by_kind: dict[str, float]  # shares asked for, by agent kind (continuous and sealed orders)
    filled_by_kind: dict[str, float]  # shares actually filled
    exec_delay: float  # mean ticks from commitment to clearing over filled sealed orders (0 if continuous)
    unrevealed: int  # sealed commitments never revealed (escrow slashed)
    slashed: float  # escrow forfeited (unrevealed or insolvent commitments)
    # Per-tick main-market activity (shock stability analysis, D-053)
    flow_main: dict[str, np.ndarray]  # by agent kind: executed net YES exposure (shares) per tick
    volume_main: dict[str, np.ndarray]  # by agent kind: executed shares per tick
    active_main: np.ndarray  # distinct agents with an executed main-market trade, per tick
    trades_main: np.ndarray  # executed main-market trades per tick
    reverts_main: np.ndarray  # reverted main-market trades per tick
    shock_false: tuple[bool, ...]  # was each shock false news?
    lmsr_surplus: float  # X-4: batch payments beyond the LMSR's cost, kept by the LMSR (0 otherwise)
    correction_ticks: tuple[int, ...]  # when each shock's status was published

    def forecaster_pnl(self) -> dict[int, float]:
        """Gross trading PnL of each researching forecaster, by forecaster index."""
        return {int(aid.rsplit("_", 1)[1]): v for aid, v in self.pnl.items() if self.kinds[aid] == "forecaster"}


def _visible_public_llr(tape: SignalTape, tick: int, latency: int | None) -> float:
    """Public LLR that becomes visible at `tick` to an agent with the given latency."""
    if latency is None or tick - latency < 0:
        return 0.0
    return float(tape.public_llr[tick - latency])


@dataclass(frozen=True)
class BlockTrace:
    """Everything that happened in one block (recorded only for replays)."""

    tick: int
    pending: list[PendingTx]
    visible: dict[str, set[int]]  # predator id -> tx_ids it could read
    plan: BlockPlan
    receipts: list[Receipt]
    price_before: float
    price_after: float
    decisions: dict[str, object] = field(default_factory=dict)  # predator id -> its best front-run (a Decision), or None


@dataclass
class MainActivity:
    """Per-tick main-market activity by agent kind (for the shock stability metrics, D-053)."""

    ticks: int
    kind_of: dict[str, str]
    flow: dict[str, np.ndarray] = field(default_factory=dict)  # signed: + = more YES exposure
    volume: dict[str, np.ndarray] = field(default_factory=dict)
    active: np.ndarray = field(init=False)  # distinct agents with an executed trade
    trades: np.ndarray = field(init=False)  # executed trades
    reverts: np.ndarray = field(init=False)  # reverted trades

    def __post_init__(self) -> None:
        self.active = np.zeros(self.ticks)
        self.trades = np.zeros(self.ticks)
        self.reverts = np.zeros(self.ticks)

    def record(self, tick: int, receipts: Sequence[Receipt]) -> None:
        traders = set()
        for r in receipts:
            if r.trade.venue is not Venue.MAIN:
                continue
            if not r.ok:
                self.reverts[tick] += 1
                continue
            kind = self.kind_of.get(r.trade.agent_id, "other")
            for series in (self.flow, self.volume):
                series.setdefault(kind, np.zeros(self.ticks))
            self.flow[kind][tick] += exposure_direction(r.trade) * abs(r.trade.shares)
            self.volume[kind][tick] += abs(r.trade.shares)
            self.trades[tick] += 1
            traders.add(r.trade.agent_id)
        self.active[tick] = len(traders)


def _receipts_by_trade(txs: Sequence[Tx], receipts: Sequence[Receipt]) -> dict[int, Receipt]:
    """Map id(trade) -> its receipt. A Bundle produces one receipt per trade, in order."""
    flat: list[Trade] = []
    for tx in txs:
        flat.extend(tx.trades if isinstance(tx, Bundle) else [tx])
    return {id(t): r for t, r in zip(flat, receipts)}


def run_market(
    cfg: SimConfig,
    rngs: RngFactory,
    market: int,
    traits: Sequence[ForecasterTraits],
    researchers: frozenset[int],
    predator_memories: Sequence[PredatorMemory] = (),
    trace: list[BlockTrace] | None = None,
    batch_log: list | None = None,
    splitting: SplittingPolicy | None = None,
) -> MarketRecord:
    tape = generate_tape(cfg, rngs, market)
    agents = build_agents(cfg, rngs, market, traits, researchers, predator_memories, splitting, tape.y)
    traders = [a for a in agents if not isinstance(a, Predator)]
    predators = [a for a in agents if isinstance(a, Predator)]
    engine = FastEngine(
        {Venue.MAIN: cfg.market.b_main, Venue.REF: cfg.market.b_ref},
        {agent.agent_id: agent.bankroll for agent in agents},
        base_fee=cfg.mempool.base_fee,
        batch_rule=cfg.mempool.clearing,
    )
    policy = MempoolPolicy(cfg.mempool.policy)
    mempool = Mempool(policy, rngs.stream("builder", market))
    builder = FeeBuilder()

    ticks = cfg.market.ticks
    price_main, price_ref = np.empty(ticks), np.empty(ticks)
    pending_receipts: dict[str, list[Receipt]] = defaultdict(list)
    last_block: tuple[Receipt, ...] = ()
    own_private_llr = tape.own_private_llr  # what each forecaster can infer from its own research
    executed = reverted = frontruns = victim_reverts = 0
    kind_of = {a.agent_id: a.kind for a in agents}
    attempts: dict[str, int] = defaultdict(int)
    reverts: dict[str, int] = defaultdict(int)
    requested: dict[str, float] = defaultdict(float)
    filled: dict[str, float] = defaultdict(float)
    activity = MainActivity(ticks, kind_of)
    desk = None
    if policy.batched:
        desk = BatchDesk(
            cfg.mempool, engine, kind_of,
            non_revealers=frozenset(a.agent_id for a in agents if isinstance(a, NonRevealGriefer)),
            free_option_groups={a.agent_id: a.group for a in agents if isinstance(a, FreeOptionTrader)},
            spammers=frozenset(a.agent_id for a in agents if isinstance(a, SpamCommitter)),
        )
        desk.log = batch_log  # None unless a replay asked for the clearings

    for tick in range(ticks):
        # 0. Sealed batches: reveal and clear the batch whose window just closed (D-046).
        batch_receipts: list[Receipt] = []
        if desk is not None:
            batch_receipts = desk.clear_if_due(tick)
            for receipt in batch_receipts:
                pending_receipts[receipt.trade.agent_id].append(receipt)
        prices = engine.prices()
        balances = engine.balances()
        depeg = cfg.market.depeg
        collateral_value = 1.0 - depeg.discount if depeg.start <= tick < depeg.end else 1.0

        def observation(agent: Agent, visible: tuple[PendingTx, ...] = (), commits: tuple = ()) -> Observation:
            private = 0.0 if agent.private_source is None else float(own_private_llr[agent.private_source, tick])
            return Observation(
                tick=tick,
                prices=prices,
                public_llr=_visible_public_llr(tape, tick, agent.public_latency),
                private_llr=private,
                account=balances[agent.agent_id],
                receipts=tuple(pending_receipts.pop(agent.agent_id, ())),
                mempool=visible,
                last_block=last_block,
                commits=commits,
                main_collateral=collateral_value,
            )

        # 1-2. Traders act; their transactions enter the mempool with arrival times.
        txs: list[Tx] = []
        for agent in traders:
            agent.perceive(observation(agent))
            txs.extend(agent.act())
        if desk is not None:  # main-market orders become sealed commitments; the rest stays continuous
            txs = desk.route(txs, tick) + desk.due_followups(tick)
            desk.commit_due(tick)
        pending = mempool.admit(txs)

        # 3. Predators read what their latency allows and respond within the same block.
        requests: list[FrontRunRequest] = []
        late: list[Tx] = []
        visible_ids: dict[str, set[int]] = {}
        decisions: dict[str, object] = {}
        for predator in predators:
            if desk is not None and isinstance(predator, MetadataPredator):
                # sealed batches: it sees commit metadata, never contents; its orders join the batch
                predator.perceive(observation(predator, commits=tuple(desk.metadata)))
                order = predator.batch_order()
                for trade in predator.act() + ([order] if order is not None else []):
                    desk.seal(trade, tick)  # unwinds first: one order per batch
                desk.commit_due(tick)
                continue
            visible = tuple(mempool.visible_to(pending, predator.latency))
            visible_ids[predator.agent_id] = {p.tx_id for p in visible}
            predator.perceive(observation(predator, visible))
            late.extend(predator.act())
            request = predator.front_run_request()
            decisions[predator.agent_id] = predator.last_decision  # kept only for replays (trace)
            if request is not None:
                requests.append(request)

        # 4-5. The builder orders the block; the engine executes it.
        plan = builder.order(pending, requests, late)
        receipts = engine.build_block(plan.txs)
        activity.record(tick, tuple(batch_receipts) + tuple(receipts))
        for receipt in receipts:
            pending_receipts[receipt.trade.agent_id].append(receipt)
            executed += receipt.ok
            reverted += not receipt.ok
            kind = kind_of.get(receipt.trade.agent_id, "other")
            attempts[kind] += 1
            reverts[kind] += not receipt.ok
            requested[kind] += abs(receipt.trade.shares)
            filled[kind] += abs(receipt.trade.shares) if receipt.ok else 0.0
        by_trade = _receipts_by_trade(plan.txs, receipts)
        for request, victim in plan.placements:
            if by_trade[id(request.front)].ok:
                frontruns += 1
                victim_reverts += not by_trade[id(victim.tx)].ok
        last_block = tuple(batch_receipts) + tuple(receipts)  # revealed batch fills are public too

        after = engine.prices()
        if trace is not None:
            trace.append(BlockTrace(tick, pending, visible_ids, plan, receipts, prices[Venue.MAIN], after[Venue.MAIN],
                                    decisions))
        price_main[tick], price_ref[tick] = after[Venue.MAIN], after[Venue.REF]

    if desk is not None:
        desk.clear_if_due(ticks, force=True)  # a batch still open at market end clears before resolution
        for kind, qty in desk.stats.requested.items():
            requested[kind] += qty
        for kind, qty in desk.stats.filled.items():
            filled[kind] += qty
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
        bankrolls={a.agent_id: a.bankroll for a in agents},
        kinds={a.agent_id: a.kind for a in agents},
        mm_pnl=engine.market_maker_pnl(),
        executed=executed,
        reverted=reverted,
        builder_revenue=engine.builder_revenue(),
        attempts_by_kind=dict(attempts),
        reverts_by_kind=dict(reverts),
        frontruns=frontruns,
        victim_reverts=victim_reverts,
        requested_by_kind=dict(requested),
        filled_by_kind=dict(filled),
        exec_delay=desk.stats.delay_sum / desk.stats.delay_count if desk and desk.stats.delay_count else 0.0,
        unrevealed=desk.stats.unrevealed if desk else 0,
        slashed=final[SLASHED_ID].cash,
        flow_main=dict(activity.flow),
        volume_main=dict(activity.volume),
        active_main=activity.active,
        trades_main=activity.trades,
        reverts_main=activity.reverts,
        shock_false=tape.shock_false,
        correction_ticks=tape.correction_ticks,
        lmsr_surplus=engine.batch_surplus,
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


def season_policy(cfg: SimConfig) -> SplittingPolicy | None:
    """The order-splitting policy forecasters share for a season, if any of them searches (E4)."""
    ex = cfg.agents.forecasters.execution
    if ex.rule not in ("expectiminimax", "crowd_expectiminimax"):
        return None
    return SplittingPolicy(OrderSplittingGame(split_params(cfg)), depth=ex.depth)


def run_season(cfg: SimConfig, seed: int, trace_market: int | None = None,
               trace: list[BlockTrace] | None = None, batch_log: list | None = None,
               splitting: SplittingPolicy | None = None) -> SeasonRecord:
    """Run a season. If `trace_market` is given, every block of that market is appended to `trace` (replays).

    `splitting` lets a caller pass the season's order-splitting policy and inspect it afterwards
    (the search benchmark does); by default it is created from the config.
    """
    rngs = RngFactory(seed)
    traits = draw_forecaster_traits(cfg, rngs)
    memory = ResearchMemory(ema=[None] * len(traits), alpha=cfg.agents.forecasters.research.ema_alpha)
    predator_memories = [PredatorMemory() for _ in range(cfg.agents.predators.count)]  # persist across markets
    splitting = splitting if splitting is not None else season_policy(cfg)
    season = SeasonRecord(seed=seed, traits=traits)
    for market in range(cfg.season.n_markets):
        researchers = decide_research(cfg, traits, memory, rngs, market)
        market_trace = trace if market == trace_market else None
        market_batches = batch_log if market == trace_market else None
        record = run_market(cfg, rngs, market, traits, researchers, predator_memories, market_trace, market_batches,
                            splitting)
        for index, gross in record.forecaster_pnl().items():
            memory.update(index, gross)
        season.markets.append(record)
    return season
