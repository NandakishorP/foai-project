"""Public-news trader: brings public information (and only that) into one venue's price."""

from __future__ import annotations

from tfs.agents.base import Observation
from tfs.agents.beliefs import Belief
from tfs.agents.kelly_trader import KellyTrader
from tfs.core.types import Venue


class PublicNewsTrader(KellyTrader):
    """Trades a single venue on public news only, after a fixed delay (DECISIONS D-019).

    On the reference venue this is how it "receives public news with a delay"
    (DECISIONS D-005). On the main market it is the agent that brings public
    news into the price under the price-anchored belief model. It uses the same
    belief model as the forecasters, so both models run with the same population.

    PEAS
    - Performance: trading profit.
    - Environment: one LMSR venue, the public news stream, other traders.
    - Actuators: buy or sell YES/NO shares on its venue.
    - Sensors: public news after `delay` ticks, its venue's price, its own account and fills.
    """

    kind = "public_news"

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
        delay: int,
    ) -> None:
        super().__init__(
            agent_id=agent_id,
            venue=venue,
            liquidity=liquidity,
            belief=belief,
            kelly_fraction=kelly_fraction,
            bankroll=bankroll,
            max_order=max_order,
            min_order=min_order,
            public_latency=delay,
        )

    def absorb(self, obs: Observation) -> None:
        self.belief.observe(obs.public_llr)
