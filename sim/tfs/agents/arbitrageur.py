"""Cross-venue arbitrageur (SPEC §6, DECISIONS D-005)."""

from __future__ import annotations

from tfs.agents.base import Agent, Observation
from tfs.core.types import Account, Bundle, Side, Trade, Tx, Venue
from tfs.market.lmsr import cost_at_price, logit


class Arbitrageur(Agent):
    """Keeps the main market and the reference venue consistent.

    Both venues pay out on the same event. If YES trades at p_lo on one venue
    and p_hi > p_lo on the other, buying x YES on the cheap venue and x NO on the
    dear one pays exactly x at resolution, whatever the outcome. The profit is
    locked in. The arbitrageur chooses x to maximise that profit, which is
    where the two prices meet (marginal profit 1 − p_lo' − (1 − p_hi') = 0). In
    LMSR log-odds, buying x YES moves the cheap venue up by x/b_lo and buying x
    NO moves the dear venue down by x/b_hi, so the prices meet at

        x = (logit p_hi − logit p_lo) / (1/b_hi + 1/b_lo).

    PEAS
    - Performance: riskless profit locked in, using limited capital.
    - Environment: two LMSR venues for the same event.
    - Actuators: atomic two-leg bundles (buy YES on one venue, NO on the other).
    - Sensors: both venues' prices, its own cash.
    """

    kind = "arbitrageur"

    def __init__(
        self, agent_id: str, liquidity: dict[Venue, float], capital: float, min_profit: float, slippage: float
    ) -> None:
        super().__init__(agent_id, bankroll=capital)
        self.liquidity = liquidity
        self.min_profit = min_profit
        self.slippage = slippage
        self._prices: dict[Venue, float] = {Venue.MAIN: 0.5, Venue.REF: 0.5}
        self._account = Account(cash=capital)

    def perceive(self, obs: Observation) -> None:
        self._prices = dict(obs.prices)
        self._account = obs.account

    def act(self) -> list[Tx]:
        bundle = self.best_bundle()
        return [bundle] if bundle is not None else []

    def best_bundle(self) -> Bundle | None:
        p_main, p_ref = self._prices[Venue.MAIN], self._prices[Venue.REF]
        if p_main == p_ref:
            return None
        cheap, dear = (Venue.REF, Venue.MAIN) if p_main > p_ref else (Venue.MAIN, Venue.REF)
        p_lo, p_hi = self._prices[cheap], self._prices[dear]
        b_lo, b_hi = self.liquidity[cheap], self.liquidity[dear]

        x = (logit(p_hi) - logit(p_lo)) / (1.0 / b_hi + 1.0 / b_lo)
        # Each YES+NO pair costs less than 1, so x shares never need more than x cash.
        x = min(x, self._account.cash)
        if x <= 0:
            return None
        cost_yes = cost_at_price(p_lo, b_lo, Side.YES, x)
        cost_no = cost_at_price(p_hi, b_hi, Side.NO, x)
        if x - cost_yes - cost_no < self.min_profit:
            return None
        return Bundle(
            self.agent_id,
            (
                Trade(self.agent_id, cheap, Side.YES, x, limit_price=cost_yes / x + self.slippage),
                Trade(self.agent_id, dear, Side.NO, x, limit_price=cost_no / x + self.slippage),
            ),
        )
