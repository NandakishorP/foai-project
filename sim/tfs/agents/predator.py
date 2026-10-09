"""MEV predator (SPEC §6): infers who is informed from public data, and front-runs them.

Two ideas drive it.

1. Belief about each address (Bayesian, partial observability). After every
   trade of address A, the predator measures its *markout*: how far the price
   kept moving in the trade's direction over the next H ticks, in log-odds,
   starting from the price right after the trade executed (D-033 amendment 1).
   The trade's own impact therefore never counts. The predator's own trades
   inside the window are subtracted exactly: in an LMSR, log-odds impacts add
   up. A markout above `markout_threshold` (0: "the price kept moving my way")
   is a success. A Beta(1, 1) prior over A's success rate θ_A is updated
   one trade at a time.
   - A noise trader's trades are followed by moves either way, so θ ≈ 0.5,
     and its posterior stays at the prior mean.
   - An informed trader's trades are followed by the market catching up, so θ > 0.5.
   - If informed trades always continue and uninformed ones half the time,
     θ = 0.5 + P(informed)/2, hence P(informed) = 2θ − 1.

2. Expected value of front-running a pending trade (utility-based decision).
   Buy x shares in the victim's direction just before it, then either hold H
   ticks and unwind at H + 1 (reference) or sell right after the victim
   (`back_run`, a sandwich). It opens no position it could not unwind before
   the market ends. Its own transactions are revert-protected (dropped, and
   free, if they would revert), as searchers' bundles are. Every step uses the LMSR closed form
   (D-033 amendment 2: the exit's slippage is inside the EV):

       EV(x) = proceeds of selling x at the expected exit price − cost of buying x now − fees
       expected exit log-odds (hold) = slot log-odds + d · victim impact
                                       + d · (1 − r) · own impact + d · P(informed) · E[drift | informed]
       expected exit log-odds (back-run) = slot log-odds + d · own impact + d · victim impact   (exact)

   r = `own_impact_reversion`: the share of its own impact the predator expects
   the market to undo before it unwinds. Its front-run carries no information,
   so informed traders and the arbitrageur push it back (reference r = 1).

   E[drift | informed] is an exponential moving average of the markouts of
   addresses currently believed informed (P > 0.5). x is chosen by grid search
   on [0, x_max]. x_max is the largest front-run that still lets the victim fill
   within its own limit: a reverted victim pays the predator nothing. It is
   also capped by the predator's cash. A fixed share of the expected gross
   profit is bid to the builder as the front-run's priority fee.

Beliefs persist across the markets of a season (`PredatorMemory`): addresses are stable.

PEAS
- Performance: trading profit net of fees and bids.
- Environment: the main LMSR market, the public mempool, the block builder, other traders.
- Actuators: front-run requests to the builder (optionally with a back-run); unwinding trades.
- Sensors: pending transactions it can read before the block is sealed (after its latency),
  public receipts of every executed trade, the main price, its own account.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from tfs.agents.base import Agent, Observation
from tfs.agents.beliefs import clipped_logit
from tfs.core.config import PredatorConfig
from tfs.core.types import Bundle, Receipt, Side, Trade, Tx, Venue
from tfs.market.lmsr import cost_at_price, sigmoid
from tfs.mempool.builder import FrontRunRequest
from tfs.mempool.mempool import PendingTx, priority_fee

GRID_POINTS = 24  # candidate front-run sizes, geometrically spaced from x_max/1000 to x_max
BISECTION_STEPS = 40  # precision of the largest size that still lets the victim fill


def exposure_direction(trade: Trade) -> int:
    """+1 if the trade increases YES exposure (buy YES or sell NO), −1 otherwise."""
    buys = trade.shares > 0
    return 1 if (trade.side is Side.YES) == buys else -1


@dataclass
class AddressBelief:
    """Beta posterior over the probability that the price keeps moving in the direction of A's trades."""

    alpha: float = 1.0
    beta: float = 1.0

    @property
    def continuation_rate(self) -> float:
        return self.alpha / (self.alpha + self.beta)

    @property
    def p_informed(self) -> float:
        """P(informed) = 2θ − 1, clipped at 0 (see module docstring)."""
        return max(0.0, 2.0 * self.continuation_rate - 1.0)

    def update(self, success: bool) -> None:
        if success:
            self.alpha += 1.0
        else:
            self.beta += 1.0


@dataclass
class PredatorMemory:
    """What a predator remembers across the markets of a season."""

    beliefs: dict[str, AddressBelief] = field(default_factory=dict)
    drift_ema: float | None = None  # E[drift | informed], in log-odds

    def belief(self, address: str) -> AddressBelief:
        return self.beliefs.setdefault(address, AddressBelief())


@dataclass
class _Watch:
    """An open markout window for one observed trade."""

    address: str
    direction: int
    start_logit: float  # log-odds right after the trade executed
    due_block: int  # the markout is read after this block
    own_impact: float = 0.0  # the predator's own log-odds impact inside the window, to subtract


@dataclass(frozen=True)
class Decision:
    """The best front-run found for one pending transaction (kept for tests and replay)."""

    victim: PendingTx
    shares: float
    ev_gross: float
    bid: float
    ev_net: float
    p_informed: float
    slot_logodds: float  # log-odds at the victim's slot, before our front-run


class Predator(Agent):
    kind = "predator"

    def __init__(self, agent_id: str, liquidity: float, cfg: PredatorConfig, memory: PredatorMemory,
                 market_ticks: int, base_fee: float = 0.0) -> None:
        super().__init__(agent_id, bankroll=cfg.capital_ratio * liquidity)
        self.b = liquidity
        self.cfg = cfg
        self.latency = cfg.latency
        self.memory = memory
        self.base_fee = base_fee
        self.market_ticks = market_ticks  # the market's end is public; positions must be unwound before it
        self._tick = 0
        self._price = 0.5
        self._cash = self.bankroll
        self._held: dict[Side, float] = {Side.YES: 0.0, Side.NO: 0.0}
        self._visible: tuple[PendingTx, ...] = ()
        self._watches: list[_Watch] = []
        self._unwinds: list[tuple[int, Side, float]] = []  # (tick due, side, shares)
        self.last_decision: Decision | None = None

    # ----------------------------------------------------------------- sensing

    def perceive(self, obs: Observation) -> None:
        self._tick = obs.tick
        self._price = obs.prices[Venue.MAIN]
        self._cash = obs.account.cash
        self._held = {side: obs.account.position(Venue.MAIN, side) for side in Side}
        self._visible = obs.mempool
        block = obs.tick - 1  # the block the receipts come from
        self._schedule_unwinds(obs.receipts)
        self._observe_block(obs.last_block, block)
        self._close_watches(block, self._price)

    def _schedule_unwinds(self, own: tuple[Receipt, ...]) -> None:
        """Each filled front-run (a buy) is sold H + 1 blocks after the block it filled in."""
        for r in own:
            if r.ok and r.trade.shares > 0 and r.trade.venue is Venue.MAIN:
                self._unwinds.append((self._tick + self.cfg.horizon, r.trade.side, r.trade.shares))

    def _observe_block(self, receipts: tuple[Receipt, ...], block: int) -> None:
        """Open a markout window for every executed main-market trade by others; charge own impact to open windows."""
        for r in receipts:
            if not r.ok or r.trade.venue is not Venue.MAIN:
                continue
            if r.trade.agent_id == self.agent_id:
                impact = clipped_logit(r.price_after) - clipped_logit(r.price_before)
                for w in self._watches:
                    w.own_impact += impact
            else:
                self._watches.append(
                    _Watch(r.trade.agent_id, exposure_direction(r.trade), clipped_logit(r.price_after),
                           block + self.cfg.horizon)
                )

    def _close_watches(self, block: int, price_now: float) -> None:
        """Read markouts whose window ended with `block`; update beliefs and E[drift | informed]."""
        still_open = []
        for w in self._watches:
            if w.due_block > block:
                still_open.append(w)
                continue
            markout = w.direction * (clipped_logit(price_now) - w.start_logit - w.own_impact)
            belief = self.memory.belief(w.address)
            belief.update(markout > self.cfg.markout_threshold)
            if belief.p_informed > 0.5:
                old = self.memory.drift_ema
                a = self.cfg.drift_ema_alpha
                self.memory.drift_ema = markout if old is None else old + a * (markout - old)
        self._watches = still_open

    # ----------------------------------------------------------------- acting

    def act(self) -> list[Tx]:
        """Unwinds that are due. They go at the end of the block, outside any open markout window's start."""
        due = [(side, shares) for t, side, shares in self._unwinds if t <= self._tick]
        self._unwinds = [u for u in self._unwinds if u[0] > self._tick]
        orders: list[Tx] = []
        for side, shares in due:
            amount = min(shares, self._held[side])
            if amount > 1e-12:
                orders.append(Trade(self.agent_id, Venue.MAIN, side, -amount, limit_price=0.0, revert_protected=True))
                self._held[side] -= amount
        return orders

    def front_run_request(self) -> FrontRunRequest | None:
        """The most profitable front-run among visible pending trades, if it beats `min_profit`."""
        self.last_decision = None
        if self._tick + self.cfg.horizon + 1 >= self.market_ticks:
            return None  # could not unwind before the market ends
        best: Decision | None = None
        for pending in self._visible:
            tx = pending.tx
            if not isinstance(tx, Trade) or tx.venue is not Venue.MAIN or tx.agent_id == self.agent_id:
                continue
            decision = self.evaluate(pending)
            if decision is not None and (best is None or decision.ev_net > best.ev_net):
                best = decision
        self.last_decision = best
        if best is None or best.ev_net < self.cfg.min_profit:
            return None
        victim = best.victim.tx
        assert isinstance(victim, Trade)
        side = Side.YES if exposure_direction(victim) > 0 else Side.NO
        avg = cost_at_price(sigmoid(best.slot_logodds), self.b, side, best.shares) / best.shares
        front = Trade(self.agent_id, Venue.MAIN, side, best.shares, avg + self.cfg.slippage,
                      priority_fee=best.bid, revert_protected=True)
        back = None
        if self.cfg.back_run:
            back = Trade(self.agent_id, Venue.MAIN, side, -best.shares, 0.0, revert_protected=True)
        return FrontRunRequest(self.agent_id, best.victim.tx_id, front, back)

    # ------------------------------------------------------------ evaluation

    def slot_logodds(self, victim: PendingTx) -> float:
        """Log-odds the victim will meet: replay the visible transactions ordered ahead of it.

        Same order as the builder (fee, then arrival). Each trade moves the
        price only if it would fill under its own limit. For an atomic Bundle,
        only its main-market legs are replayed.
        """
        logodds = clipped_logit(self._price)
        ahead = sorted(self._visible, key=lambda p: (-priority_fee(p.tx), p.arrival))
        for p in ahead:
            if p.tx_id == victim.tx_id:
                break
            trades = p.tx.trades if isinstance(p.tx, Bundle) else (p.tx,)
            for t in trades:
                if t.venue is Venue.MAIN and self._fills(t, logodds):
                    logodds += exposure_direction(t) * abs(t.shares) / self.b
        return logodds

    def evaluate(self, pending: PendingTx) -> Decision | None:
        victim = pending.tx
        assert isinstance(victim, Trade)
        d = exposure_direction(victim)
        side = Side.YES if d > 0 else Side.NO
        slot = self.slot_logodds(pending)
        budget = self._cash - 2 * self.base_fee
        x_max = min(self._largest_front_run(victim, d, slot), self._affordable(side, slot, budget))
        if x_max <= 0:
            return None
        p_inf = self.memory.belief(victim.agent_id).p_informed
        drift = self.memory.drift_ema or 0.0
        # Geometric spacing: sensible sizes range from a few shares (small victims) to hundreds.
        sizes = np.geomspace(x_max / 1000.0, x_max, GRID_POINTS)
        evs = [self.ev_gross(x, victim, d, side, slot, p_inf * drift) for x in sizes]
        i = int(np.argmax(evs))
        x, ev_gross = float(sizes[i]), float(evs[i])
        if ev_gross <= 0:
            return None
        bid = self.cfg.bid_share * ev_gross
        if cost_at_price(sigmoid(slot), self.b, side, x) + bid > budget:  # the bid must be paid too
            x = self._affordable(side, slot, budget - bid)
            ev_gross = self.ev_gross(x, victim, d, side, slot, p_inf * drift)
            bid = self.cfg.bid_share * ev_gross
            if x <= 0 or ev_gross <= 0:
                return None
        return Decision(pending, x, ev_gross, bid, ev_gross - bid, p_inf, slot)

    def ev_gross(self, x: float, victim: Trade, d: int, side: Side, slot: float, expected_drift: float) -> float:
        """Expected profit of front-running `victim` with x shares at log-odds `slot`.

        Net of the exit's LMSR slippage and of base fees; not yet net of the bid.
        """
        cost = cost_at_price(sigmoid(slot), self.b, side, x)
        own_impact, victim_impact = d * x / self.b, d * abs(victim.shares) / self.b
        if self.cfg.back_run:  # sell straight after the victim: nothing has had time to change
            exit_logodds = slot + own_impact + victim_impact
        else:
            remaining_own = (1.0 - self.cfg.own_impact_reversion) * own_impact
            exit_logodds = slot + remaining_own + victim_impact + d * expected_drift
        proceeds = -cost_at_price(sigmoid(exit_logodds), self.b, side, -x)
        return proceeds - cost - 2 * self.base_fee  # two transactions: in and out

    def _fills(self, trade: Trade, logodds: float) -> bool:
        """Would this trade meet its own limit at this price?"""
        paid = cost_at_price(sigmoid(logodds), self.b, trade.side, trade.shares)
        if trade.shares > 0:
            return paid / trade.shares <= trade.limit_price
        return (-paid) / (-trade.shares) >= trade.limit_price

    def _largest_front_run(self, victim: Trade, d: int, slot: float) -> float:
        """Largest x (bisection) such that the victim still fills after our front-run of x shares."""
        if not self._fills(victim, slot):
            return 0.0
        lo, hi = 0.0, self.b * 10.0  # 10 log-odds: far beyond any limit
        if self._fills(victim, slot + d * hi / self.b):
            return hi
        for _ in range(BISECTION_STEPS):
            mid = (lo + hi) / 2
            if self._fills(victim, slot + d * mid / self.b):
                lo = mid
            else:
                hi = mid
        return lo

    def _affordable(self, side: Side, slot: float, budget: float) -> float:
        """Largest x whose cost at log-odds `slot` fits in `budget` (bisection)."""
        if budget <= 0:
            return 0.0
        price = sigmoid(slot)
        side_price = price if side is Side.YES else 1.0 - price
        lo, hi = 0.0, budget / side_price  # each share costs at least the current price of its side
        for _ in range(BISECTION_STEPS):
            mid = (lo + hi) / 2
            if cost_at_price(price, self.b, side, mid) <= budget:
                lo = mid
            else:
                hi = mid
        return lo
