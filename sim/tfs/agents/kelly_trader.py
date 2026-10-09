"""Shared trading core for informed agents: belief -> fractional-Kelly target -> one order per tick."""

from __future__ import annotations

from tfs.agents.base import Agent, Observation
from tfs.agents.beliefs import Belief, clipped_logit
from tfs.agents.execution import exposure_trade
from tfs.agents.kelly import kelly_target_net_yes
from tfs.core.types import Account, Trade, Tx, Venue


class KellyTrader(Agent):
    """Trades one venue toward its fractional-Kelly target, only ever in the direction of its edge.

    Execution rule: never make a trade with negative expected value under the
    agent's own belief. Concretely:
    - trade only in the direction belief − price points;
    - stop at the Kelly target exposure;
    - never push the price past the belief (size is capped by the LMSR closed form);
    - set the limit price at the belief, so being front-run can at worst cancel the order.

    Subclasses decide which signals feed the belief (`absorb`).
    """

    def __init__(
        self,
        agent_id: str,
        venue: Venue,
        liquidity: float,
        belief: Belief,
        kelly_fraction: float,
        bankroll: float,
        max_order: float,
        min_order: float,
        public_latency: int | None,
        private_source: int | None = None,
    ) -> None:
        super().__init__(agent_id, bankroll, public_latency, private_source)
        self.venue = venue
        self.liquidity = liquidity  # the venue's LMSR b (a public contract parameter)
        self.belief = belief
        self.kelly_fraction = kelly_fraction
        self.max_order = max_order
        self.min_order = min_order
        self._price = 0.5
        self._account = Account(cash=bankroll)

    def absorb(self, obs: Observation) -> None:
        """Feed this tick's evidence into the belief. Overridden by subclasses."""
        raise NotImplementedError

    def perceive(self, obs: Observation) -> None:
        for receipt in obs.receipts:
            if receipt.ok and receipt.trade.venue is self.venue:
                self.belief.on_own_fill(receipt)
        self.absorb(obs)
        self._price = obs.prices[self.venue]
        self._account = obs.account

    def act(self) -> list[Tx]:
        trade = self.next_trade()
        return [trade] if trade is not None else []

    def next_trade(self) -> Trade | None:
        price = self._price
        belief = self.belief.probability(price)
        if belief == price:
            return None
        direction = 1 if belief > price else -1

        target = kelly_target_net_yes(belief, price, self.kelly_fraction, self.bankroll)
        shortfall = (target - self._account.net_yes(self.venue)) * direction
        if shortfall <= 0:
            return None  # already at (or beyond) the Kelly target in the edge direction
        push_cap = abs(self.liquidity * (clipped_logit(belief) - clipped_logit(price)))
        size = min(shortfall, self.max_order, push_cap)
        if size < self.min_order:
            return None

        # Limit at the belief: YES is worth `belief` to us, NO is worth 1 − belief.
        yes_value, no_value = belief, 1.0 - belief
        buy_limit = yes_value if direction > 0 else no_value
        sell_limit = no_value if direction > 0 else yes_value
        return exposure_trade(self.agent_id, self.venue, self._account, direction, size, buy_limit, sell_limit)
