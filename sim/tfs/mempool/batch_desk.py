"""Routing main-market orders into sealed batches (commit_reveal / zk_batch; DECISIONS D-046).

Under a batch policy, agents behave exactly as before: they return `Trade`s. The desk
turns each main-market trade into a sealed buy order and commits it to the current
batch with an escrow tier. Every K blocks it reveals and clears the batch through the
engine. Reference-venue trades stay continuous.

Rules, in plain words:
- **Buys only.** Selling S at no less than L is the same exposure change as buying the
  other side at no more than 1 − L, so a sell becomes that buy (pairs are merged later).
- **One order per identity per batch** (the nullifier). Noise traders are exempt: each
  noise agent stands for a crowd of independent small users.
- **Escrow tier:** the smallest tier covering size × limit. Orders larger than the top
  tier, or than the agent can escrow, are cut to fit.
- **ZK proving delay:** a zk_batch order is committed `proving_delay` ticks after the
  decision; if the window has closed by then, it joins the next batch.
- **Legged arbitrage:** a two-venue bundle's main leg is sealed; its reference leg is sent
  in the block after clearing, scaled by the main leg's fill.
- **Visible metadata:** each commitment shows its block, escrow tier and, unless a
  relayer is used, its sender. Its contents stay hidden until the reveal.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field, replace

from tfs.core.config import MempoolConfig
from tfs.core.types import Bundle, Receipt, Side, Trade, Tx, Venue
from tfs.engines.fast import FastEngine
from tfs.market.batch import SealedOrder

LIMIT_MIN, LIMIT_MAX = 0.001, 0.999  # sealed limits must lie strictly inside (0, 1) (circuit constraint)
CROWD_KINDS = frozenset({"noise"})  # agents that stand for many users: not limited to one order per batch


@dataclass(frozen=True)
class CommitMeta:
    """What anyone can see about a commitment before the reveal."""

    batch: int
    tick: int
    sender: str | None  # None when sent through a relayer
    tier: float  # escrow posted


@dataclass
class _Entry:
    order: SealedOrder
    escrow: float
    commit_tick: int
    reveal: bool = True  # attackers may withhold the reveal
    followup: Trade | None = None  # legged arbitrage: the other venue's leg


@dataclass
class DeskStats:
    requested: dict[str, float] = field(default_factory=lambda: defaultdict(float))  # shares, by agent kind
    filled: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    delay_sum: float = 0.0  # Σ (clearing tick − commit tick) over filled orders
    delay_count: int = 0
    unrevealed: int = 0
    batches: int = 0


def to_sealed(trade: Trade, order_id: int) -> SealedOrder:
    """A buy-only sealed order with the same exposure change as `trade`."""
    if trade.shares > 0:
        side, size, limit = trade.side, trade.shares, trade.limit_price
    else:
        side, size, limit = trade.side.other, -trade.shares, 1.0 - trade.limit_price
    return SealedOrder(order_id, trade.agent_id, side, size, min(LIMIT_MAX, max(LIMIT_MIN, limit)))


class BatchDesk:
    def __init__(self, cfg: MempoolConfig, engine: FastEngine, kinds: dict[str, str],
                 non_revealers: frozenset[str] = frozenset(), free_option_groups: dict[str, str] | None = None,
                 spammers: frozenset[str] = frozenset()) -> None:
        self.zk = cfg.policy == "zk_batch"
        self.non_revealers = non_revealers
        self.free_option_groups = free_option_groups or {}
        self.spammers = spammers
        self.K = cfg.batch_interval
        self.tiers = cfg.escrow_tiers
        self.delay = cfg.proving_delay if cfg.policy == "zk_batch" else 0
        self.sender_visible = cfg.sender_visible
        self.engine = engine
        self.kinds = kinds
        self.book: list[_Entry] = []
        self.queue: list[tuple[int, _Entry]] = []  # (tick it can be committed, entry): waiting for a proof
        self.followups: list[tuple[int, Trade]] = []
        self.metadata: list[CommitMeta] = []  # commitments of the batch currently open
        self.stats = DeskStats()
        self._next_id = 0
        # optional record of every clearing (for replaying batches on another engine)
        self.log: list[tuple[list[tuple[SealedOrder, float]], list[tuple[str, float]]]] | None = None

    def batch_of(self, tick: int) -> int:
        return tick // self.K

    # ------------------------------------------------------------- incoming

    def route(self, txs: Sequence[Tx], tick: int) -> list[Tx]:
        """Seal main-market orders; return what stays continuous (reference-venue trades)."""
        continuous: list[Tx] = []
        for tx in txs:
            if isinstance(tx, Bundle):
                main = [t for t in tx.trades if t.venue is Venue.MAIN]
                other = [t for t in tx.trades if t.venue is not Venue.MAIN]
                if main:
                    self.seal(main[0], tick, followup=other[0] if other else None)
                else:
                    continuous.append(tx)
            elif tx.venue is Venue.MAIN:
                self.seal(tx, tick)
            else:
                continuous.append(tx)
        return continuous

    def seal(self, trade: Trade, tick: int, reveal: bool = True, followup: Trade | None = None) -> bool:
        """Queue a sealed order for commitment (after the proving delay). False if not allowed this batch."""
        agent = trade.agent_id
        if agent in self.spammers and self.zk:
            return False  # no valid proof exists for an insolvent order
        reveal = reveal and agent not in self.non_revealers
        commit_tick = tick + self.delay
        if self.kinds.get(agent) not in CROWD_KINDS and self._has_order(agent, self.batch_of(commit_tick)):
            return False  # one order per identity per batch
        order = to_sealed(trade, self._next_id)
        self._next_id += 1
        self.queue.append((commit_tick, _Entry(order, 0.0, commit_tick, reveal, followup)))
        return True

    def _has_order(self, agent: str, batch: int) -> bool:
        in_book = any(e.order.agent_id == agent and self.batch_of(e.commit_tick) == batch for e in self.book)
        queued = any(e.order.agent_id == agent and self.batch_of(t) == batch for t, e in self.queue)
        return in_book or queued

    def commit_due(self, tick: int) -> None:
        """Commit every queued order whose proof is ready: choose an escrow tier and lock it."""
        still = []
        for due, entry in self.queue:
            if due > tick:
                still.append((due, entry))
                continue
            sized = self._spam_escrow(entry.order) if entry.order.agent_id in self.spammers else self._fit_escrow(entry.order)
            if sized is None:
                continue
            order, tier = sized
            if not self.engine.commit(order.agent_id, tier):
                continue
            entry.order, entry.escrow, entry.commit_tick = order, tier, tick
            self.book.append(entry)
            self.stats.requested[self.kinds.get(order.agent_id, "other")] += order.size
            sender = order.agent_id if self.sender_visible else None
            self.metadata.append(CommitMeta(self.batch_of(tick), tick, sender, tier))
        self.queue = still

    def _fit_escrow(self, order: SealedOrder) -> tuple[SealedOrder, float] | None:
        """Smallest tier covering the worst-case cost; cut the order to the largest affordable tier if needed."""
        cash = self.engine.balances()[order.agent_id].cash - self.engine.base_fee
        affordable = [t for t in self.tiers if t <= cash]
        if not affordable:
            return None
        worst = order.size * order.limit
        covering = [t for t in affordable if t >= worst]
        tier = covering[0] if covering else affordable[-1]
        size = min(order.size, tier / order.limit)
        return replace(order, size=size), tier

    def _spam_escrow(self, order: SealedOrder) -> tuple[SealedOrder, float] | None:
        """A spam commitment posts only the smallest tier, whatever the order's worst-case cost."""
        tier = self.tiers[0]
        cash = self.engine.balances()[order.agent_id].cash - self.engine.base_fee
        return (order, tier) if cash >= tier else None

    def _decide_free_option_reveals(self, entries: list[_Entry]) -> None:
        """Each free-option pair reveals only the side the honest reveals push the batch towards."""
        honest = [e for e in entries if e.reveal and e.order.agent_id not in self.free_option_groups]
        net = sum(e.order.size if e.order.side is Side.YES else -e.order.size for e in honest)
        wanted = Side.YES if net > 0 else Side.NO if net < 0 else None
        for e in entries:
            if e.order.agent_id in self.free_option_groups:
                e.reveal = e.order.side is wanted

    # -------------------------------------------------------------- clearing

    def due_followups(self, tick: int) -> list[Tx]:
        due = [t for when, t in self.followups if when <= tick]
        self.followups = [(when, t) for when, t in self.followups if when > tick]
        return due

    def clear_if_due(self, tick: int, force: bool = False) -> list[Receipt]:
        """At the first block after a batch window (or at market end), reveal and clear the open batch."""
        if not force and (tick == 0 or tick % self.K != 0):
            return []
        closing = self.batch_of(tick) - (0 if force else 1)
        entries = [e for e in self.book if self.batch_of(e.commit_tick) <= closing]
        if not entries:
            return []
        self.book = [e for e in self.book if self.batch_of(e.commit_tick) > closing]
        self.metadata = [m for m in self.metadata if m.batch > closing]
        if self.free_option_groups:
            self._decide_free_option_reveals(entries)
        revealed = [(e.order, e.escrow) for e in entries if e.reveal]
        unrevealed = [(e.order.agent_id, e.escrow) for e in entries if not e.reveal]
        self.stats.unrevealed += len(unrevealed)
        self.stats.batches += 1
        if self.log is not None:
            self.log.append((list(revealed), list(unrevealed)))
        receipts = self.engine.clear_batch(revealed, unrevealed)  # one receipt per revealed order, same order
        for e, r in zip([e for e in entries if e.reveal], receipts):
            filled = r.trade.shares
            self.stats.filled[self.kinds.get(r.trade.agent_id, "other")] += filled
            if filled > 0:
                self.stats.delay_sum += tick - e.commit_tick
                self.stats.delay_count += 1
                if e.followup is not None:  # legged arbitrage: send the other leg next block, scaled
                    scaled = replace(e.followup, shares=e.followup.shares * filled / e.order.size)
                    self.followups.append((tick + 1, scaled))
        return receipts
