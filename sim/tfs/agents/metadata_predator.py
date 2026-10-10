"""Metadata copy-trading predator: the ZK_BATCH-arm counterpart of the reference predator (H3a; D-046).

Under sealed batches the predator can no longer read orders, and everyone in a batch
trades at one uniform price, so there is nothing to front-run. What it can still see:
- **commit metadata:** who commits (unless a relayer hides the sender), in which block,
  and with which escrow tier (a coarse size bucket);
- **revealed orders** after each batch: direction, size and fill of every order, which
  feed the same per-address Beta posteriors as the reference predator. Markouts start
  at the post-clearing price, and the predator's own later trades are subtracted (D-033).

Strategy: for every address it keeps μ_A, an exponential moving average of A's own
markouts: how far the price kept moving A's way after A's past batch fills. That is
A's expected continuation. In the last block of each commit window (earlier by the ZK
proving delay, so that its own proof is ready in time), it predicts the batch's
post-clearing move from the metadata:

    Δ = Σ_A tier_A · d_A · μ_A / Σ_A tier_A   (log-odds; d_A = A's last revealed direction),

over the committing addresses it can identify. If the expected value of joining the
batch in the direction of Δ beats its costs, it commits an EV-maximising order to the
same batch. The expected exit keeps the expected impact of the direction-aligned
escrow plus |Δ|, and loses the predator's own impact (r = own_impact_reversion = 1,
the pessimistic reference assumption, D-037). It unwinds after H + 1 ticks by buying
the other side; the pair merges back to cash.

(First version: weighted addresses by P(informed) and learned drift only from addresses
with P > 0.5. Under batching no address passes that gate, so the strategy never traded.
Replaced before any E3 run; DECISIONS D-047.)

All parameters are the reference predator's (D-034); no new tunable numbers are added.

PEAS
- Performance: trading profit.
- Environment: the sealed-batch main market, its public commit metadata and revealed orders.
- Actuators: sealed buy orders (one per batch).
- Sensors: commit metadata of the open batch, revealed batch receipts, the main price, its own account.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from tfs.agents.base import Observation
from tfs.agents.beliefs import clipped_logit
from tfs.agents.predator import GRID_POINTS, PredatorMemory, _Watch, exposure_direction
from tfs.agents.predator import Predator as _ReferencePredator
from tfs.core.config import PredatorConfig
from tfs.core.types import Receipt, Side, Trade, Tx, Venue
from tfs.market.lmsr import cost_at_price, sigmoid
from tfs.mempool.batch_desk import CommitMeta


class MetadataPredator(_ReferencePredator):
    kind = "predator"

    def __init__(self, agent_id: str, liquidity: float, cfg: PredatorConfig, memory: PredatorMemory,
                 market_ticks: int, batch_interval: int, proving_delay: int) -> None:
        super().__init__(agent_id, liquidity, cfg, memory, market_ticks)
        self.K = batch_interval
        self.proving_delay = proving_delay
        self._commits: tuple[CommitMeta, ...] = ()
        self.last_direction: dict[str, int] = {}  # from revealed orders
        self.last_signal = 0.0

    # ----------------------------------------------------------------- sensing

    def perceive(self, obs: Observation) -> None:
        self._commits = obs.commits
        for r in obs.last_block:
            if r.requested is not None and r.trade.agent_id != self.agent_id:  # a revealed sealed order
                self.last_direction[r.trade.agent_id] = exposure_direction(
                    Trade(r.trade.agent_id, r.trade.venue, r.trade.side, 1.0, r.trade.limit_price))
        super().perceive(obs)

    def _observe_block(self, receipts: tuple[Receipt, ...], block: int) -> None:
        """Batch-aware markouts.

        A revealed fill opens a window at the post-clearing price. The predator's own fill in the
        same batch is already inside that starting price, so it is not subtracted again. Only its
        own fills in *later* blocks are charged to open windows, at their own size (d·filled/b),
        not the whole batch's move.
        """
        opened_now: list[_Watch] = []
        own_impact = 0.0
        for r in receipts:
            if not r.ok or r.trade.venue is not Venue.MAIN:
                continue
            if r.trade.agent_id == self.agent_id:
                own_impact += exposure_direction(r.trade) * abs(r.trade.shares) / self.b
            else:
                opened_now.append(_Watch(r.trade.agent_id, exposure_direction(r.trade),
                                         clipped_logit(r.price_after), block + self.cfg.horizon))
        for w in self._watches:
            w.own_impact += own_impact
        self._watches.extend(opened_now)

    # ----------------------------------------------------------------- acting

    def act(self) -> list[Tx]:
        """Unwinds that are due (sold by buying the other side; the desk turns sells into such buys)."""
        return super().act()

    def front_run_request(self):  # noqa: D102 - no front-running under uniform-price batches
        return None

    def batch_order(self) -> Trade | None:
        """The order to commit to the open batch, decided in the last block the proof allows."""
        if (self._tick + self.proving_delay) % self.K != self.K - 1:
            return None
        if self._tick + self.cfg.horizon + 1 + self.K >= self.market_ticks:
            return None  # could not unwind before the market ends
        move, aligned_cash = self._predicted_move(self._commits)
        self.last_signal = move
        if move == 0.0:
            return None
        d = 1 if move > 0 else -1
        side = Side.YES if d > 0 else Side.NO
        price = self._price
        side_price = price if side is Side.YES else 1.0 - price
        informed_shares = aligned_cash / max(side_price, 1e-6)  # escrow tiers bound what the aligned side may buy
        drift = abs(move)
        best_x, best_ev = 0.0, 0.0
        cap = self._affordable(side, clipped_logit(price), self._cash)
        if cap <= 0:
            return None
        for x in np.geomspace(cap / 1000.0, cap, GRID_POINTS):
            ev = self._ev(float(x), d, side, informed_shares, drift)
            if ev > best_ev:
                best_x, best_ev = float(x), ev
        if best_ev < self.cfg.min_profit:
            return None
        start = clipped_logit(price) + d * informed_shares / self.b
        avg = cost_at_price(sigmoid(start), self.b, side, best_x) / best_x
        return Trade(self.agent_id, Venue.MAIN, side, best_x, min(0.999, avg + self.cfg.slippage))

    def _predicted_move(self, commits: Sequence[CommitMeta]) -> tuple[float, float]:
        """(predicted post-batch YES log-odds move Δ, escrow committed in the direction of Δ)."""
        known = [(c.tier, self.last_direction[c.sender], self.memory.markout_ema.get(c.sender, 0.0))
                 for c in commits
                 if c.sender is not None and c.sender != self.agent_id and c.sender in self.last_direction]
        weight = sum(tier for tier, _, _ in known)
        if weight == 0:
            return 0.0, 0.0  # a relayer hides senders, or nobody known has committed
        move = sum(tier * d * mu for tier, d, mu in known) / weight
        if move == 0.0:
            return 0.0, 0.0
        direction = 1 if move > 0 else -1
        return move, sum(tier for tier, d, _ in known if d == direction)

    def _close_watches(self, block: int, price_now: float) -> None:
        """As the reference predator, plus a per-address EMA of markouts (expected continuation)."""
        a = self.cfg.drift_ema_alpha
        for w in self._watches:
            if w.due_block <= block:
                markout = w.direction * (clipped_logit(price_now) - w.start_logit - w.own_impact)
                old = self.memory.markout_ema.get(w.address)
                self.memory.markout_ema[w.address] = markout if old is None else old + a * (markout - old)
        super()._close_watches(block, price_now)

    def _ev(self, x: float, d: int, side: Side, informed_shares: float, drift: float) -> float:
        """Buy x in the batch behind the informed demand; exit later with own impact undone (r) and drift added."""
        start = clipped_logit(self._price) + d * informed_shares / self.b
        cost = cost_at_price(sigmoid(start), self.b, side, x)  # ≈ uniform price after the informed demand and ours
        exit_logodds = start + d * (1.0 - self.cfg.own_impact_reversion) * x / self.b + d * drift
        proceeds = -cost_at_price(sigmoid(exit_logodds), self.b, side, -x)
        return proceeds - cost - 2 * self.base_fee
