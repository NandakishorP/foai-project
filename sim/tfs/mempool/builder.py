"""The block builder: decides the order of transactions in a block (SPEC §3, §6 "Builder").

The builder maximises its revenue:
- Plain transactions are ordered by priority fee, highest first. Ties go to
  earlier arrival, so a block with no tips is in arrival order.
- A predator can ask for a placement: put my front-run immediately before
  transaction V, and optionally my back-run immediately after it. The tip
  (the front-run's priority fee) is the bid. Only one predator can sit in
  front of a given victim, so the highest bid wins (ties: lowest agent id, for
  determinism).

Placement is not atomic with the victim (priority-gas-auction style,
DECISIONS D-033). Each transaction executes, and pays, on its own. A front-run
can fill while its victim reverts, at the predator's risk.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from tfs.core.types import Trade, Tx
from tfs.mempool.mempool import PendingTx, priority_fee


@dataclass(frozen=True)
class FrontRunRequest:
    """A predator's request to be placed around one pending victim transaction."""

    agent_id: str
    victim_id: int
    front: Trade
    back: Trade | None = None  # sandwich variant: sell right after the victim

    @property
    def bid(self) -> float:
        return self.front.priority_fee


@dataclass(frozen=True)
class BlockPlan:
    txs: list[Tx]  # final order sent to the engine
    placements: list[tuple[FrontRunRequest, PendingTx]] = field(default_factory=list)  # winning requests and victims


class FeeBuilder:
    def order(
        self,
        pending: Sequence[PendingTx],
        requests: Sequence[FrontRunRequest] = (),
        late_txs: Sequence[Tx] = (),
    ) -> BlockPlan:
        """Order a block: fee-sorted pending transactions, winning placements around their victims,
        then `late_txs` (transactions sent after the mempool snapshot, e.g. predator unwinds) at the end."""
        by_id = {p.tx_id: p for p in pending}
        winners: dict[int, FrontRunRequest] = {}
        # Highest bid first; among equal bids, alphabetical agent id. The first request seen per victim wins.
        for req in sorted(requests, key=lambda r: (-r.bid, r.agent_id)):
            if req.victim_id in by_id and req.victim_id not in winners:
                winners[req.victim_id] = req

        txs: list[Tx] = []
        for p in sorted(pending, key=lambda p: (-priority_fee(p.tx), p.arrival)):
            req = winners.get(p.tx_id)
            if req is not None:
                txs.append(req.front)
            txs.append(p.tx)
            if req is not None and req.back is not None:
                txs.append(req.back)
        txs.extend(late_txs)
        placements = [(winners[i], by_id[i]) for i in sorted(winners)]
        return BlockPlan(txs=txs, placements=placements)
