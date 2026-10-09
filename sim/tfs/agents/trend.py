"""Trend follower (SPEC §6, required by Topic 6): momentum on the main market price."""

from __future__ import annotations

from tfs.agents.base import Agent, Observation
from tfs.agents.execution import exposure_trade
from tfs.core.types import Account, Tx, Venue


class TrendFollower(Agent):
    """Classic moving-average crossover on the main market price.

    It tracks a fast and a slow exponential moving average of the price. Fast
    above slow by more than `threshold` signals an uptrend, so it goes long YES
    up to `max_position`. Fast below slow signals a downtrend, so it goes long
    NO. In between it holds. It trades `order_size` shares per tick with market
    orders. It knows nothing about the event, so it can amplify moves, which
    the shock experiments examine.

    PEAS
    - Performance: trading profit.
    - Environment: the main LMSR market.
    - Actuators: market buy/sell orders of YES/NO on the main market.
    - Sensors: the main market price history and its own account.
    """

    kind = "trend"

    def __init__(
        self,
        agent_id: str,
        fast_span: int,
        slow_span: int,
        threshold: float,
        order_size: float,
        max_position: float,
        bankroll: float,
    ) -> None:
        super().__init__(agent_id, bankroll)
        # Standard EMA weight for a span of n periods: alpha = 2 / (n + 1).
        self.alpha_fast = 2.0 / (fast_span + 1)
        self.alpha_slow = 2.0 / (slow_span + 1)
        self.warmup = slow_span  # ticks before the slow average means anything
        self.threshold = threshold
        self.order_size = order_size
        self.max_position = max_position
        self.fast: float | None = None
        self.slow: float | None = None
        self.seen = 0
        self._account = Account(cash=bankroll)

    def perceive(self, obs: Observation) -> None:
        price = obs.prices[Venue.MAIN]
        if self.fast is None or self.slow is None:
            self.fast = self.slow = price
        else:
            self.fast += self.alpha_fast * (price - self.fast)
            self.slow += self.alpha_slow * (price - self.slow)
        self.seen += 1
        self._account = obs.account

    def target_position(self) -> float | None:
        """Desired net YES exposure, or None to hold the current position."""
        if self.seen < self.warmup or self.fast is None or self.slow is None:
            return None
        gap = self.fast - self.slow
        if gap > self.threshold:
            return self.max_position
        if gap < -self.threshold:
            return -self.max_position
        return None

    def act(self) -> list[Tx]:
        target = self.target_position()
        if target is None:
            return []
        delta = target - self._account.net_yes(Venue.MAIN)
        if abs(delta) < 1e-9:
            return []
        direction = 1 if delta > 0 else -1
        size = min(abs(delta), self.order_size)
        return [exposure_trade(self.agent_id, Venue.MAIN, self._account, direction, size, buy_limit=1.0, sell_limit=0.0)]
