"""Whale manipulator (SPEC §6; E5): spends a budget to hold the main price at a target.

From tick `start` to tick `end` the whale pushes the main market's YES price to
`target` every block. It buys NO when the price is above the target and YES when below,
in exactly the amount that moves the LMSR price to the target (closed form:
b·(logit target − logit price) shares). It never spends more than its budget in total.
It knows nothing about the outcome and does not unwind: it holds its shares to
resolution, so its loss is what it paid to move the price away from where informed
traders keep pushing it.

Informed forecasters, the public-news trader and the arbitrageur see a price away from
their beliefs and trade it back. They are the ones who collect the whale's loss. E5
measures how far, for how long, at what cost, and who profits.

PEAS
- Performance: how closely and how long the price stays at the target (its objective);
  its trading loss is the cost, reported, not minimised.
- Environment: the main LMSR market and everyone else trading on it.
- Actuators: buy orders of YES or NO on the main market.
- Sensors: the main market price, the clock, its own cash.
"""

from __future__ import annotations

from tfs.agents.base import Agent, Observation
from tfs.core.config import WhaleConfig
from tfs.core.types import Side, Trade, Tx, Venue
from tfs.market.lmsr import affordable_shares, logit


def yes_target(cfg: WhaleConfig, outcome: int) -> float:
    """The YES price the whale defends. In the E5 scenario (against_truth) it backs the wrong
    outcome: it holds the price of the outcome that will happen at `target`. The scenario
    chooses this side; the whale itself never observes the outcome."""
    if not cfg.against_truth:
        return cfg.target
    return cfg.target if outcome == 1 else 1.0 - cfg.target


class WhaleManipulator(Agent):
    kind = "whale"

    def __init__(self, agent_id: str, liquidity: float, budget: float, target: float, start: int, end: int,
                 bankroll: float) -> None:
        super().__init__(agent_id, bankroll)
        self.b = liquidity
        self.budget = budget  # most cash it will spend in total
        self.target = target
        self.window = range(start, end)
        self.spent = 0.0
        self._tick = 0
        self._price = 0.5

    def perceive(self, obs: Observation) -> None:
        self._tick = obs.tick
        self._price = obs.prices[Venue.MAIN]
        for receipt in obs.receipts:  # count only what actually filled
            if receipt.ok:
                self.spent += receipt.cost

    def act(self) -> list[Tx]:
        if self._tick not in self.window or self.spent >= self.budget:
            return []
        shares = self.b * (logit(self.target) - logit(self._price))  # > 0: buy YES; < 0: buy NO
        side = Side.YES if shares > 0 else Side.NO
        size = abs(shares)
        side_price = self._price if side is Side.YES else 1.0 - self._price
        size = min(size, affordable_shares(side_price, self.b, self.budget - self.spent))  # never past the budget
        if size < 0.5:
            return []
        return [Trade(self.agent_id, Venue.MAIN, side, size, limit_price=1.0)]
