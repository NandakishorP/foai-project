"""Binary LMSR (Hanson's logarithmic market scoring rule), in floating point.

The market maker tracks q_yes and q_no, the outstanding YES and NO shares.

    cost  C(q) = b * ln(exp(q_yes / b) + exp(q_no / b))
    price p_yes = exp(q_yes / b) / (exp(q_yes / b) + exp(q_no / b)) = sigmoid((q_yes - q_no) / b)

A trader buying Δ shares pays C(q after) − C(q before); selling is buying a
negative amount. Prices always sum to 1, and the market maker's worst-case loss
is b·ln 2 (SPEC §4).

The only quantity that sets the YES price is the share imbalance (q_yes − q_no)/b.
Moving the price from p to p' therefore takes b·(logit p' − logit p) YES shares,
a closed form that agents use to size orders.

This is the Python mirror of the Solidity LMSRMarket (Phase 2b). Floats are used
here; the differential test will state the tolerance against fixed point.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from tfs.core.types import Side


def _logaddexp(a: float, c: float) -> float:
    """ln(e^a + e^c) without overflow (the log-sum-exp trick)."""
    hi = max(a, c)
    return hi + math.log(math.exp(a - hi) + math.exp(c - hi))


def sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


def logit(p: float) -> float:
    return math.log(p / (1.0 - p))


def cost(q_yes: float, q_no: float, b: float) -> float:
    return b * _logaddexp(q_yes / b, q_no / b)


def price_yes(q_yes: float, q_no: float, b: float) -> float:
    return sigmoid((q_yes - q_no) / b)


def trade_cost(q_yes: float, q_no: float, b: float, side: Side, shares: float) -> float:
    """Cash the trader pays to buy `shares` of `side` (negative shares = sell, negative result = proceeds)."""
    if side is Side.YES:
        return cost(q_yes + shares, q_no, b) - cost(q_yes, q_no, b)
    return cost(q_yes, q_no + shares, b) - cost(q_yes, q_no, b)


def yes_shares_to_move_price(p_from: float, p_to: float, b: float) -> float:
    """YES shares to buy (negative: NO shares to buy) that move the YES price from p_from to p_to.

    Buying x NO shares moves the YES log-odds by −x/b, exactly as selling x YES does.
    """
    return b * (logit(p_to) - logit(p_from))


def max_market_maker_loss(b: float) -> float:
    return b * math.log(2.0)


@dataclass
class LmsrMarket:
    """Mutable LMSR state of one venue. `collateral` is the cash the market maker has received."""

    b: float
    q_yes: float = 0.0
    q_no: float = 0.0
    collateral: float = 0.0

    def price(self) -> float:
        return price_yes(self.q_yes, self.q_no, self.b)

    def quote(self, side: Side, shares: float) -> float:
        return trade_cost(self.q_yes, self.q_no, self.b, side, shares)

    def execute(self, side: Side, shares: float) -> float:
        """Apply a trade and return its cost to the trader."""
        paid = self.quote(side, shares)
        if side is Side.YES:
            self.q_yes += shares
        else:
            self.q_no += shares
        self.collateral += paid
        return paid

    def payout(self, y: int) -> float:
        """Total owed to holders of the winning side at resolution."""
        return self.q_yes if y == 1 else self.q_no
