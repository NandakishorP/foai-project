"""Attackers on sealed batches (SPEC §5.1 costs; descriptive E3-V variants, D-046).

None of them try to profit from information. They measure what a sealed-batch design
costs and what a validity proof adds over plain commit-reveal (D-003):
- `NonRevealGriefer`: commits every batch and never reveals. Its escrow is slashed;
  the question is whether its hidden commitments change the clearing for others.
- `FreeOptionTrader`: two staked identities (two agents sharing a group) commit opposite
  sides every batch. After seeing the honest reveals, the desk reveals only the side
  the batch is moving towards and lets the other be slashed. ZK's nullifier allows one
  order per identity, not per person, so this works under both policies; only the
  slashing deters it.
- `SpamCommitter`: commits orders whose worst-case cost exceeds their escrow.
  commit_reveal catches them only at reveal (slashed); under zk_batch no valid proof
  exists, so they never enter the batch.

PEAS (all three)
- Performance: none optimised; their PnL and their effect on other traders are measured.
- Environment: the sealed-batch main market.
- Actuators: sealed commitments (and, through the desk, reveal decisions).
- Sensors: none needed (free-option decisions use the batch's public reveals, applied by the desk).
"""

from __future__ import annotations

import numpy as np

from tfs.agents.base import Agent, Observation
from tfs.core.types import Side, Trade, Tx, Venue


class _BatchAttacker(Agent):
    kind = "attacker"

    def __init__(self, agent_id: str, size: float, bankroll: float, batch_interval: int) -> None:
        super().__init__(agent_id, bankroll)
        self.size = size
        self.K = batch_interval
        self._tick = 0

    def perceive(self, obs: Observation) -> None:
        self._tick = obs.tick

    def _first_tick_of_batch(self) -> bool:
        return self._tick % self.K == 0


class NonRevealGriefer(_BatchAttacker):
    def __init__(self, agent_id: str, size: float, bankroll: float, batch_interval: int,
                 rng: np.random.Generator) -> None:
        super().__init__(agent_id, size, bankroll, batch_interval)
        self.rng = rng

    def act(self) -> list[Tx]:
        if not self._first_tick_of_batch():
            return []
        side = Side.YES if self.rng.random() < 0.5 else Side.NO
        return [Trade(self.agent_id, Venue.MAIN, side, self.size, 0.5)]


class FreeOptionTrader(_BatchAttacker):
    """One of the two identities of a free-option attacker: it always commits `side`; the desk decides the reveal."""

    def __init__(self, agent_id: str, group: str, side: Side, size: float, bankroll: float, batch_interval: int) -> None:
        super().__init__(agent_id, size, bankroll, batch_interval)
        self.group = group
        self.side = side

    def act(self) -> list[Tx]:
        if not self._first_tick_of_batch():
            return []
        return [Trade(self.agent_id, Venue.MAIN, self.side, self.size, 0.9)]


class SpamCommitter(_BatchAttacker):
    def act(self) -> list[Tx]:
        if not self._first_tick_of_batch():
            return []
        return [Trade(self.agent_id, Venue.MAIN, Side.YES, self.size, 0.9)]  # the desk escrows only the smallest tier
