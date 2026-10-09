"""Noise trader (SPEC §6): uninformed random orders that provide liquidity and price noise."""

from __future__ import annotations

import numpy as np

from tfs.agents.base import Agent, Observation
from tfs.core.types import Side, Trade, Tx, Venue


class NoiseTrader(Agent):
    """Buys random amounts of a random side at Poisson-distributed times.

    Noise traders give informed traders someone to profit from, and they make
    the price noisy, so informed traders cannot be identified trivially.

    PEAS
    - Performance: none optimised (they trade for exogenous reasons such as
      hedging or entertainment); their losses are reported.
    - Environment: one LMSR venue.
    - Actuators: market buy orders of YES or NO.
    - Sensors: none used (they ignore prices and news).
    """

    kind = "noise"

    def __init__(
        self, agent_id: str, venue: Venue, rate: float, mean_size: float, bankroll: float, rng: np.random.Generator
    ) -> None:
        super().__init__(agent_id, bankroll)
        self.venue = venue
        self.rate = rate
        self.mean_size = mean_size
        self.rng = rng

    def perceive(self, obs: Observation) -> None:
        pass

    def act(self) -> list[Tx]:
        orders: list[Tx] = []
        for _ in range(self.rng.poisson(self.rate)):
            side = Side.YES if self.rng.random() < 0.5 else Side.NO
            size = float(self.rng.exponential(self.mean_size))
            orders.append(Trade(self.agent_id, self.venue, side, size, limit_price=1.0))
        return orders
