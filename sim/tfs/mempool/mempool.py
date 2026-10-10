"""The mempool: where transactions wait, who can see them, and when (SPEC §3.2).

Agents never submit straight to the chain; they submit to this mempool. Within
a block interval (one tick), transactions arrive in a random order spread
evenly over the interval: arrival times are (rank + 0.5) / n for a seeded
random permutation. The builder seals the block at time 1.

Visibility policy PUBLIC: an observer with latency ℓ sees a pending
transaction's full contents (sender, side, size, limit price) iff
arrival + ℓ < 1, i.e. it learns about the transaction while there is still
time to act before the block is sealed. Phase 3 adds PRIVATE_RELAY,
COMMIT_REVEAL and ZK_BATCH behind the same interface.

The permutation comes from the same "builder" random stream that ordered
Phase 1 blocks. With no predators and zero fees, blocks are therefore ordered
exactly as in Phase 1 (regression-tested).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

import numpy as np

from tfs.core.types import Bundle, Trade, Tx


class MempoolPolicy(str, Enum):
    PUBLIC = "public"  # everyone can read pending transactions (after their latency)
    PRIVATE_RELAY = "private_relay"  # orders go straight to a trusted builder: nobody else sees them
    COMMIT_REVEAL = "commit_reveal"  # main-market orders are sealed commitments (escrow + slashing, no proof)
    ZK_BATCH = "zk_batch"  # sealed commitments with a validity proof (D-046)

    @property
    def batched(self) -> bool:
        return self in (MempoolPolicy.COMMIT_REVEAL, MempoolPolicy.ZK_BATCH)


@dataclass(frozen=True)
class PendingTx:
    tx_id: int  # unique within a market
    tx: Tx
    arrival: float  # time within the block interval, in [0, 1)

    @property
    def sender(self) -> str:
        return self.tx.agent_id


def priority_fee(tx: Tx) -> float:
    if isinstance(tx, Bundle):
        return max((t.priority_fee for t in tx.trades), default=0.0)
    return tx.priority_fee


class Mempool:
    def __init__(self, policy: MempoolPolicy, rng: np.random.Generator) -> None:
        self.policy = policy
        self.rng = rng
        self._next_id = 0

    def admit(self, txs: Sequence[Tx]) -> list[PendingTx]:
        """Stamp this tick's transactions with ids and arrival times (a random order, evenly spaced)."""
        n = len(txs)
        order = self.rng.permutation(n)  # drawn every tick, even when n = 0, to keep the stream aligned
        rank = np.empty(n, dtype=int)
        rank[order] = np.arange(n)
        pending = [PendingTx(self._next_id + i, tx, (rank[i] + 0.5) / n) for i, tx in enumerate(txs)]
        self._next_id += n
        return pending

    def visible_to(self, pending: Sequence[PendingTx], latency: float) -> list[PendingTx]:
        """The pending transactions an observer with this latency can read before the block is sealed."""
        if self.policy is MempoolPolicy.PUBLIC:
            return [p for p in pending if p.arrival + latency < 1.0]
        # Private relay: nothing is public before inclusion. Batch policies: main-market orders are
        # sealed, and what predators may see of them is the commit metadata (BatchDesk), not this list.
        return []


def is_plain_trade(p: PendingTx) -> bool:
    return isinstance(p.tx, Trade)
