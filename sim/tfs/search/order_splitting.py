"""The order-splitting game (SPEC §6.1): how an informed trader should slice its order against a predator.

A forecaster wants to buy R more shares in the direction of its edge (its Kelly shortfall)
before the edge disappears. Every slice it sends is visible in the public mempool, so a
predator can trade ahead of it. This module is the forecaster's *internal model* of that
situation, solved by expectiminimax (tfs.search.expectiminimax) every block, replanning
from the new state each time (a receding horizon).

One block of the game:
1. **MAX** (the forecaster) picks a slice q ∈ {0, R/8, R/4, R/2, R}, never more than the
   "push cap" b·g that would take the price to its belief (as KellyTrader). Its limit is
   its belief, so a slice never fills at a loss.
2. **MIN** (the predator) sees the slice and picks a front-run f ∈ {0, x_max/2, x_max}.
   - x_max is the largest front-run after which the slice still fills (the real predator's
     cap: a reverted victim pays it nothing), and what its cash affords.
   - It is the *rational worst case* (DECISIONS D-053, D-054). It may only pick front-runs
     it expects to profit from, under the real predator's own EV formula (`front_run_ev`,
     r = 1). Its beliefs are the ones the reference predator actually holds about
     forecasters in the baseline: P(informed) and E[drift | informed], measured by
     `tfs measure-env`. Among those front-runs it picks the one that hurts MAX most.
     - A pure zero-sum MIN would push every slice to its limit regardless of its own
       loss, which makes the game degenerate.
     - So would an omniscient MIN (P(informed) = 1, drift = the whole gap) at the
       measured competitor push: every slice is then worth about 0 (D-054).
3. The slice executes after the front-run. MAX earns q·(belief − average price paid).
4. **CHANCE**, then the next block:
   - other researchers close a fraction κ of the remaining gap (measured in the
     no-predator baseline; DECISIONS D-053);
   - the predator's own impact is undone, as the predator itself assumes (r = 1);
   - noise traders move the price ±σ (probability ½ each);
   - public news arrives with probability λ and moves belief *and* price by ±h. It
     points the way MAX believes with probability = MAX's belief. Both move by the same
     log-odds, so news changes the price level, not the gap.

**Crowd-aware variant** (EXPLORATORY X-5, D-057). With `crowd_ahead` set, a CHANCE layer
sits between MAX and MIN: the other researchers with the same signal close a random share
of the gap *before* MAX's slice executes (five equally likely values, measured on the
baseline). If they already pushed the price to MAX's limit, the slice reverts and earns
nothing. The rest of the block's closure by everyone else is `kappa` (then `kappa_rest`).
Without `crowd_ahead` the game is exactly the E4 game.

Everything is in the YES direction: a NO edge is mirrored first. States are snapped to a
grid (price and belief in steps of `logit_step`; R on a geometric grid), so that equal
states are *exactly* equal. That makes the transposition table exact, and lets the
forecaster reuse a solved state (`SplittingPolicy`).

At the depth cut-off, the heuristic assumes MAX sends everything now and MIN replies with
its worst allowed front-run: "remaining quantity × expected adverse impact" (SPEC).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum

from tfs.agents.predator import front_run_ev
from tfs.core.config import SimConfig
from tfs.core.types import Side
from tfs.market.lmsr import affordable_shares, cost_at_price, highest_logodds_to_fill, sigmoid
from tfs.search.expectiminimax import Node, Options, Searcher, Stats

SLICE_FRACTIONS = (0.0, 1 / 8, 1 / 4, 1 / 2, 1.0)  # SPEC §6.1: {0, Q/8, Q/4, Q/2, remaining}


@dataclass(frozen=True)
class SplitParams:
    """The forecaster's model of its environment. Values come from the config (`split_params`)."""

    b: float  # main-market LMSR liquidity
    kappa: float  # share of the remaining gap other traders close per block
    noise_sigma: float  # per-block noise-trader move, in log-odds
    news_prob: float  # chance of a public news item per block
    news_size: float  # log-odds a typical news item moves belief and price
    predator_cash: float
    predator_p_informed: float  # the predator's belief that a forecaster is informed (measured)
    predator_drift: float  # its E[drift | informed] in log-odds (measured)
    bid_share: float  # share of its expected profit the predator bids to the builder
    predator_min_profit: float
    min_order: float  # smallest slice worth sending
    logit_step: float  # grid for belief and price
    size_ratio: float  # geometric grid for R
    max_depth: int  # deepest search used (makes the value bounds valid)
    crowd_ahead: tuple[float, ...] = ()  # X-5: equally likely shares of the gap the crowd closes before MAX's slice


def split_params(cfg: SimConfig) -> SplitParams:
    """Derive the game's parameters from the simulation config.

    - noise σ: the noise traders' net flow per block is a sum of Poisson-many exponential
      orders, with variance count·rate·E[size²] = count·rate·2·mean²; divided by b in log-odds.
    - news: one public item per block with probability `rate`. Its typical size is the
      expected LLR per item: expected_nats · precision_scale / (rate · ticks).
    - predator: the reference predator's cash, bid share and minimum profit, and its
      measured beliefs (from `execution`).
    """
    a, info, ex = cfg.agents, cfg.information, cfg.agents.forecasters.execution
    b = cfg.market.b_main
    noise = a.noise_main
    crowd = ex.rule == "crowd_expectiminimax"  # X-5: the crowd ahead is a chance node; kappa is what remains
    return SplitParams(
        b=b,
        kappa=ex.crowd_kappa if crowd else ex.kappa,
        noise_sigma=math.sqrt(noise.count * noise.rate * 2.0 * noise.mean_size ** 2) / b,
        news_prob=info.public.rate,
        news_size=info.public.expected_nats * info.precision_scale / (info.public.rate * cfg.market.ticks),
        predator_cash=a.predators.capital_ratio * b,
        predator_p_informed=ex.predator_p_informed,
        predator_drift=ex.predator_drift,
        bid_share=a.predators.bid_share,
        predator_min_profit=a.predators.min_profit,
        min_order=a.forecasters.min_order,
        logit_step=ex.logit_step,
        size_ratio=ex.size_ratio,
        max_depth=ex.depth,
        crowd_ahead=tuple(ex.crowd_ahead) if crowd else (),
    )


class Phase(Enum):
    MAX = "max"
    CROWD = "crowd"  # X-5 only: a chance node
    MIN = "min"
    CHANCE = "chance"


@dataclass(frozen=True)
class SplitState:
    phase: Phase
    belief: float  # MAX's belief, log-odds (on the grid)
    price: float  # YES log-odds (on the grid at MAX nodes)
    remaining: float  # shares still to buy (R; at MIN nodes it still includes the slice)
    slice: float = 0.0  # the slice MAX chose (MIN and CHANCE nodes)
    fresh: bool = False  # news just arrived: only steers move ordering, never the value


@dataclass
class OrderSplittingGame:
    """The game, in the interface of tfs.search.expectiminimax.Game."""

    params: SplitParams
    _min_cache: dict[tuple[float, float, float], list[float]] = field(default_factory=dict)

    # ------------------------------------------------------------ grid

    def snap_logit(self, x: float) -> float:
        return round(x / self.params.logit_step) * self.params.logit_step

    def snap_size(self, r: float) -> float:
        """Nearest point of the geometric grid min_order · ratio^k (0 below min_order)."""
        p = self.params
        if r < p.min_order:
            return 0.0
        k = round(math.log(r / p.min_order) / math.log(p.size_ratio))
        return p.min_order * p.size_ratio ** k

    def root(self, belief: float, price: float, remaining: float, fresh: bool = False) -> SplitState:
        """A MAX state on the grid, mirrored so the edge is towards YES."""
        if belief < price:
            belief, price = -belief, -price
        return SplitState(Phase.MAX, self.snap_logit(belief), self.snap_logit(price), self.snap_size(remaining),
                          fresh=fresh)

    # ------------------------------------------------------------ the rules

    def node(self, s: SplitState) -> Node:
        if s.phase is Phase.MAX and (s.remaining < self.params.min_order or s.belief <= s.price):
            return Node.TERMINAL  # nothing left to buy, or no edge left in this direction
        return {Phase.MAX: Node.MAX, Phase.CROWD: Node.CHANCE, Phase.MIN: Node.MIN, Phase.CHANCE: Node.CHANCE}[s.phase]

    def push_cap(self, s: SplitState) -> float:
        """Shares that take the price exactly to the belief (KellyTrader's cap)."""
        return self.params.b * (s.belief - s.price)

    def actions(self, s: SplitState, ordered: bool) -> list[float]:
        if s.phase is Phase.MAX:
            sizes = sorted({min(f * s.remaining, self.push_cap(s)) for f in SLICE_FRACTIONS})
            sizes = [q for q in sizes if q == 0.0 or q >= self.params.min_order]
            return sizes[::-1] if (ordered and s.fresh) else sizes  # after news, big slices first
        fronts = self._allowed_front_runs(s)
        return fronts[::-1] if ordered else fronts  # the most damaging front-run first

    def result(self, s: SplitState, action: float) -> tuple[float, SplitState]:
        if s.phase is Phase.MAX:
            nxt = Phase.CROWD if self.params.crowd_ahead else Phase.MIN
            return 0.0, SplitState(nxt, s.belief, s.price, s.remaining, slice=action, fresh=s.fresh)
        if not self._fills(s, front=action):  # X-5 only: the crowd took the price past MAX's limit
            return 0.0, SplitState(Phase.CHANCE, s.belief, s.price, s.remaining, fresh=s.fresh)
        return self._execute(s, front=action), SplitState(
            Phase.CHANCE, s.belief, s.price + s.slice / self.params.b, s.remaining - s.slice, fresh=s.fresh)

    def outcomes(self, s: SplitState) -> list[tuple[float, SplitState]]:
        p = self.params
        if s.phase is Phase.CROWD:  # X-5: the same-signal crowd trades ahead of MAX's slice
            share = 1.0 / len(p.crowd_ahead)
            # snapped to the grid like every other price, so repeated states hit the transposition table
            return [(share, SplitState(Phase.MIN, s.belief, self.snap_logit(s.price + a * (s.belief - s.price)),
                                       s.remaining, slice=s.slice, fresh=s.fresh)) for a in p.crowd_ahead]
        pushed = s.price + p.kappa * (s.belief - s.price)  # other traders close part of the gap
        up = sigmoid(s.belief)  # MAX's own probability that news points to YES
        news = [(1.0 - p.news_prob, 0.0), (p.news_prob * up, p.news_size), (p.news_prob * (1.0 - up), -p.news_size)]
        out = []
        for noise in (-p.noise_sigma, p.noise_sigma):
            for prob, shift in news:
                nxt = SplitState(Phase.MAX, self.snap_logit(s.belief + shift), self.snap_logit(pushed + noise + shift),
                                 self.snap_size(s.remaining), fresh=shift != 0.0)
                out.append((0.5 * prob, nxt))
        return out

    def heuristic(self, s: SplitState) -> float:
        """Send everything now; the predator replies with its worst allowed front-run.

        In the crowd-aware game (X-5) the crowd trades first, so the estimate is averaged over
        the crowd's outcomes, from the price each leaves.
        """
        if not self.params.crowd_ahead:
            return self._send_all_now(s.belief, s.price, s.remaining)
        return sum(self._send_all_now(s.belief, s.price + a * (s.belief - s.price), s.remaining)
                   for a in self.params.crowd_ahead) / len(self.params.crowd_ahead)

    def _send_all_now(self, belief: float, price: float, remaining: float) -> float:
        q = min(remaining, self.params.b * (belief - price))
        if q < self.params.min_order:
            return 0.0
        at_min = SplitState(Phase.MIN, belief, price, remaining, slice=q)
        return min(self._execute(at_min, f) for f in self._allowed_front_runs(at_min))

    def bounds(self, s: SplitState) -> tuple[float, float]:
        """0 ≤ value ≤ R × the largest edge per share any descendant can have.

        A slice never fills at a loss, so 0 is a floor. Per share, MAX earns at most
        sigmoid(belief) − sigmoid(price) ≤ tanh(gap / 4), the largest at a symmetric level.
        The gap only shrinks, except by noise and grid rounding: at most σ + one step per block.
        """
        p = self.params
        widest = (s.belief - s.price) + p.max_depth * (p.noise_sigma + p.logit_step)
        return 0.0, s.remaining * math.tanh(max(widest, 0.0) / 4.0)

    def key(self, s: SplitState) -> tuple:
        return (s.phase, s.belief, s.price, s.remaining, s.slice)  # `fresh` never changes a value

    # ------------------------------------------------------------ helpers

    def _execute(self, s: SplitState, front: float) -> float:
        """MAX's profit on its slice after a front-run of `front` shares."""
        if s.slice == 0.0:
            return 0.0
        paid = cost_at_price(sigmoid(s.price + front / self.params.b), self.params.b, Side.YES, s.slice)
        return max(0.0, s.slice * sigmoid(s.belief) - paid)  # max(): rounding at exactly the limit

    def _fills(self, s: SplitState, front: float) -> bool:
        """Does MAX's slice still meet its limit? Always true in the E4 game (by construction); X-5 checks it."""
        if not self.params.crowd_ahead or s.slice == 0.0:
            return True
        paid = cost_at_price(sigmoid(s.price + front / self.params.b), self.params.b, Side.YES, s.slice)
        return paid <= s.slice * sigmoid(s.belief) + 1e-9

    def _allowed_front_runs(self, s: SplitState) -> list[float]:
        """MIN's options {0, x_max/2, x_max}, keeping only those the predator expects to profit from."""
        key = (s.belief, s.price, s.slice)
        if key in self._min_cache:
            return self._min_cache[key]
        p = self.params
        fronts = [0.0]
        if s.slice > 0.0:
            fill_limit = highest_logodds_to_fill(s.slice, sigmoid(s.belief), p.b)
            x_max = min(p.b * (fill_limit - s.price), affordable_shares(sigmoid(s.price), p.b, p.predator_cash))
            drift = p.predator_p_informed * p.predator_drift  # what the real predator expects
            for f in (x_max / 2.0, x_max):
                if f <= 0.0:
                    continue
                ev = front_run_ev(f, p.b, Side.YES, 1, s.price, s.slice, 1.0, drift, False, 0.0)
                if ev * (1.0 - p.bid_share) >= p.predator_min_profit:
                    fronts.append(f)
        self._min_cache[key] = fronts
        return fronts


@dataclass
class SplittingPolicy:
    """The forecaster's slice decision: the search's first move at the (snapped) current state.

    Solved states are remembered, together with the search's transposition table, for as
    long as this object lives (one season, owned by the simulation, never global). The
    search is exact on the grid state; mapping the real state to its grid point is the only
    approximation.
    """

    game: OrderSplittingGame
    depth: int
    options: Options = Options()
    searcher: Searcher = field(init=False)
    decisions: dict[tuple, float] = field(default_factory=dict)  # root key -> fraction of R to send
    roots_solved: int = 0

    def __post_init__(self) -> None:
        self.searcher = Searcher(self.game, self.options)

    @property
    def stats(self) -> Stats:
        return self.searcher.stats

    def slice(self, belief: float, price: float, remaining: float, fresh: bool = False) -> float:
        """Shares to send now (same direction as the edge), out of the `remaining` shortfall."""
        root = self.game.root(belief, price, remaining, fresh)
        if self.game.node(root) is Node.TERMINAL:
            return 0.0
        key = self.game.key(root)
        if key not in self.decisions:
            q, _ = self.searcher.best_action(root, self.depth)
            self.decisions[key] = q / root.remaining
            self.roots_solved += 1
        cap = self.game.params.b * abs(belief - price)
        return min(self.decisions[key] * remaining, cap)
