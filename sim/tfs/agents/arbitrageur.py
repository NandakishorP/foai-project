"""Cross-venue arbitrageur (SPEC §6, DECISIONS D-005)."""

from __future__ import annotations

from tfs.agents.base import Agent, Observation
from tfs.core.types import Account, Bundle, Side, Trade, Tx, Venue
from tfs.market.lmsr import cost_at_price, logit, sigmoid


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

    **Depeg** (shock scenario S-D, DECISIONS D-053). If the main market's collateral is
    worth v < 1 dollars while the reference venue's is worth 1, the pair no longer pays
    a riskless dollar. It pays x·v or x·1 dollars depending on the outcome. The arbitrageur
    counts dollars and only locks in what it is sure of: worst-case payout min(v_lo, v_hi)·x
    minus the dollar cost. Its best size is where the marginal pair costs exactly that
    worst-case payout (found by bisection). Small gaps are no longer worth trading, so
    arbitrage withdraws. With equal collateral values this is exactly the formula above.
    Simplification: its cash is one account; only its valuation uses dollars.

    PEAS
    - Performance: riskless profit locked in, using limited capital.
    - Environment: two LMSR venues for the same event.
    - Actuators: atomic two-leg bundles (buy YES on one venue, NO on the other).
    - Sensors: both venues' prices, its own cash, the dollar value of the main market's collateral.
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
        self._value: dict[Venue, float] = {Venue.MAIN: 1.0, Venue.REF: 1.0}  # dollars per unit of collateral
        self._account = Account(cash=capital)

    def perceive(self, obs: Observation) -> None:
        self._prices = dict(obs.prices)
        self._value = {Venue.MAIN: obs.main_collateral, Venue.REF: 1.0}
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

        v_lo, v_hi = self._value[cheap], self._value[dear]

        x = (logit(p_hi) - logit(p_lo)) / (1.0 / b_hi + 1.0 / b_lo)  # where the two prices meet
        if v_lo != v_hi:
            x = self._worst_case_size(p_lo, p_hi, b_lo, b_hi, v_lo, v_hi, x)
        # Each YES+NO pair costs less than 1, so x shares never need more than x cash.
        x = min(x, self._account.cash)
        if x <= 0:
            return None
        cost_yes = cost_at_price(p_lo, b_lo, Side.YES, x)
        cost_no = cost_at_price(p_hi, b_hi, Side.NO, x)
        locked_in = min(x * v_lo, x * v_hi) - cost_yes * v_lo - cost_no * v_hi  # dollars, whatever the outcome
        if locked_in < self.min_profit:
            return None
        return Bundle(
            self.agent_id,
            (
                Trade(self.agent_id, cheap, Side.YES, x, limit_price=cost_yes / x + self.slippage),
                Trade(self.agent_id, dear, Side.NO, x, limit_price=cost_no / x + self.slippage),
            ),
        )

    @staticmethod
    def _worst_case_size(p_lo: float, p_hi: float, b_lo: float, b_hi: float, v_lo: float, v_hi: float,
                         x_meet: float) -> float:
        """Size where one more pair costs (in dollars) exactly its worst-case payout min(v_lo, v_hi).

        The marginal pair costs v_lo·(cheap venue's YES price) + v_hi·(dear venue's NO price);
        both rise with x, so bisection works. At x_meet the prices meet and the marginal pair
        already costs at least the worst case, so the answer lies in [0, x_meet].
        """
        worst = min(v_lo, v_hi)
        l_lo, l_hi = logit(p_lo), logit(p_hi)

        def marginal_cost(x: float) -> float:
            return v_lo * sigmoid(l_lo + x / b_lo) + v_hi * (1.0 - sigmoid(l_hi - x / b_hi))

        if marginal_cost(0.0) >= worst:
            return 0.0
        lo, hi = 0.0, x_meet
        for _ in range(50):
            mid = (lo + hi) / 2
            if marginal_cost(mid) < worst:
                lo = mid
            else:
                hi = mid
        return lo
