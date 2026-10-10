"""Informed forecaster (SPEC §6): pays for research, updates beliefs, trades by fractional Kelly."""

from __future__ import annotations

from tfs.agents.base import Observation
from tfs.agents.beliefs import Belief, PriceAnchoredBelief
from tfs.agents.kelly_trader import KellyTrader
from tfs.agents.slicing import SliceRule
from tfs.core.types import Venue


class InformedForecaster(KellyTrader):
    """A forecaster that chose to research this market.

    PEAS
    - Performance: trading profit in this market, net of research cost; over a
      season, the research decision (`ResearchMemory`) maximises expected net profit.
    - Environment: the main LMSR market; a stochastic stream of public news
      and of its own private signals; other traders whose orders move the price.
    - Actuators: buy or sell YES/NO shares on the main market (one order per tick). How
      much of its Kelly shortfall it sends each tick is its slice rule (E4): by default a
      fixed cap; with `expectiminimax`, the first move of the order-splitting game
      against a predator (adversarial search, tfs.search).
    - Sensors: its own private signals (immediately), public news (after
      `public_latency` ticks), the main market price, and its own account and fills.

    Belief (DECISIONS D-013): under `own_signals` it adds every public and
    private signal to its prior log-odds. Under `price_anchored` it adds only its
    private signals to the price. Public news reaches the price through the
    public-news trader, and counting it again here would double-count it.

    Forecasters that do not research sit the market out entirely (DECISIONS D-014),
    so every instance of this class is researching.
    """

    kind = "forecaster"

    def __init__(
        self,
        index: int,
        liquidity: float,
        belief: Belief,
        kelly_fraction: float,
        bankroll: float,
        max_order: float,
        min_order: float,
        public_latency: int,
        slice_rule: SliceRule | None = None,
    ) -> None:
        super().__init__(
            agent_id=f"forecaster_{index}",
            venue=Venue.MAIN,
            liquidity=liquidity,
            belief=belief,
            kelly_fraction=kelly_fraction,
            bankroll=bankroll,
            max_order=max_order,
            min_order=min_order,
            public_latency=public_latency,
            private_source=index,
            slice_rule=slice_rule,
        )
        self.index = index
        self.uses_public_news = not isinstance(belief, PriceAnchoredBelief)

    def absorb(self, obs: Observation) -> None:
        self.belief.observe(obs.private_llr)
        if self.uses_public_news:
            self.belief.observe(obs.public_llr)
