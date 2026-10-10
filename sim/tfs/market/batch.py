"""Uniform-price batch clearing against the LMSR, with a pro-rata margin (DECISIONS D-046).

A batch collects sealed *buy* orders: buy YES with a limit L (the most it pays per YES
share), or buy NO with a limit L (the most it pays per NO share). Everyone in the batch
trades at one YES price p:
- a YES buyer pays p per share and is willing iff p ≤ L;
- a NO buyer pays 1 − p per share and is willing iff p ≥ 1 − L.
Each order therefore has a *bound* on p: an upper bound for YES, a lower bound for NO.

Matched YES/NO pairs are complete sets, paid for by their two buyers (p + (1 − p) = 1).
Only the net imbalance D = YES filled − NO filled trades with the LMSR. The uniform
price is the LMSR's *average* price for that imbalance:
    D > 0:  p = [C(q_yes + D, q_no) − C(q)] / D
    D < 0:  1 − p = [C(q_yes, q_no + |D|) − C(q)] / |D|
    D = 0:  p = the current marginal price.
With this choice the payments exactly cover the sets plus the LMSR cost (budget balance).

The clearing price p* is a fixed point: p* = avgprice(D(p*)), where D(p) is the net
demand of the orders whose bounds allow p. As p rises, YES orders drop out and NO orders
come in, so D(p) only falls, while avgprice(D) rises with D. There is exactly one
crossing, found by walking the "price ladder" of order bounds:
- between two consecutive bounds D is constant; if avgprice(D) lies strictly inside
  that interval, every active order fills fully at p* = avgprice(D);
- otherwise the crossing is exactly at a bound b. Orders strictly inside fill fully. The
  orders whose bound equals b (the margin) are rationed so that avgprice(D) = b holds
  exactly: first as many matched YES/NO pairs as possible, then the excess side
  pro-rata (every order on that side gets the same fraction).
Researchers who share one signal send identical limits. Under D-004's "drop all violated
orders" they were all dropped together; here they share the fill pro-rata.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from tfs.core.types import Side
from tfs.market.lmsr import cost, cost_at_price, price_yes

BISECTION_STEPS = 200  # enough to pin D to float precision over any realistic range
_TIE = 1e-12  # bounds closer than this are treated as equal


@dataclass(frozen=True)
class SealedOrder:
    order_id: int
    agent_id: str
    side: Side  # what is bought
    size: float  # shares, > 0
    limit: float  # max average price per share of `side`, in (0, 1)

    @property
    def bound(self) -> float:
        """The YES-price bound: upper for a YES buyer, lower for a NO buyer."""
        return self.limit if self.side is Side.YES else 1.0 - self.limit

    def accepts(self, p: float) -> bool:
        return p <= self.bound + _TIE if self.side is Side.YES else p >= self.bound - _TIE


@dataclass(frozen=True)
class Clearing:
    price_yes: float  # the uniform YES price p*
    net_yes: float  # D: YES shares bought from the LMSR (negative: NO shares)
    lmsr_cost: float  # cash paid to the LMSR for |D| shares
    fills: dict[int, float]  # order_id -> shares filled (0 if not)

    def paid(self, order: SealedOrder) -> float:
        """Cash this order pays for its fill."""
        unit = self.price_yes if order.side is Side.YES else 1.0 - self.price_yes
        return unit * self.fills.get(order.order_id, 0.0)


def average_price(q_yes: float, q_no: float, b: float, d: float) -> float:
    """YES-equivalent average price of trading a net imbalance d with the LMSR.

    Uses the closed form from the current price (log1p/expm1), not a difference of two
    nearly equal costs, which would cancel catastrophically for small d and mislead the bisection.
    """
    p = price_yes(q_yes, q_no, b)
    if abs(d) < 1e-15:
        return p
    if d > 0:
        return cost_at_price(p, b, Side.YES, d) / d
    return 1.0 - cost_at_price(p, b, Side.NO, -d) / (-d)


def _imbalance_for_price(q_yes: float, q_no: float, b: float, p: float, lo: float, hi: float) -> float:
    """The d in [lo, hi] whose average price equals p (average price increases with d), by bisection."""
    for _ in range(BISECTION_STEPS):
        mid = (lo + hi) / 2
        if average_price(q_yes, q_no, b, mid) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _active(o: SealedOrder, p: float) -> bool:
    """Does the order's bound strictly allow price p?"""
    return o.bound > p + _TIE if o.side is Side.YES else o.bound < p - _TIE


def _demand(orders: Sequence[SealedOrder], p: float, strict: bool) -> float:
    """Net YES demand of orders whose bounds allow price p (strictly, if `strict`)."""
    d = 0.0
    for o in orders:
        if o.side is Side.YES and (o.bound > p + _TIE if strict else o.bound >= p - _TIE):
            d += o.size
        elif o.side is Side.NO and (o.bound < p - _TIE if strict else o.bound <= p + _TIE):
            d -= o.size
    return d


def clear_batch(orders: Sequence[SealedOrder], q_yes: float, q_no: float, b: float) -> Clearing:
    """Clear a batch of sealed buy orders at one uniform price (see module docstring)."""
    if not orders:
        return Clearing(price_yes(q_yes, q_no, b), 0.0, 0.0, {})
    bounds = sorted({0.0, 1.0, *(o.bound for o in orders)})

    # 1. An interval between consecutive bounds whose constant demand prices inside it.
    for lo, hi in zip(bounds[:-1], bounds[1:]):
        mid = (lo + hi) / 2
        d = _demand(orders, mid, strict=True)
        p = average_price(q_yes, q_no, b, d)
        if lo < p < hi:
            # exactly the orders that make up d: those whose bounds allow every price in the interval
            fills = {o.order_id: (o.size if _active(o, mid) else 0.0) for o in orders}
            return _clearing(p, d, fills, q_yes, q_no, b)

    # 2. Otherwise the crossing sits on a bound b. Orders strictly inside fill fully. The marginal
    #    orders (bound == b) are rationed: as many matched YES/NO pairs as possible (each side pays
    #    exactly b or 1 − b), then the excess side pro-rata, so the LMSR imbalance hits the fixed point.
    for bound in bounds[1:-1]:
        d_strict = _demand(orders, bound, strict=True)
        margin = [o for o in orders if abs(o.bound - bound) <= _TIE]
        yes_m = sum(o.size for o in margin if o.side is Side.YES)
        no_m = sum(o.size for o in margin if o.side is Side.NO)
        lo_d, hi_d = d_strict - no_m, d_strict + yes_m  # every reachable imbalance at price b
        if not (average_price(q_yes, q_no, b, lo_d) - _TIE <= bound <= average_price(q_yes, q_no, b, hi_d) + _TIE):
            continue
        d_star = _imbalance_for_price(q_yes, q_no, b, bound, lo_d, hi_d)
        extra = d_star - d_strict  # net YES the margin must contribute
        yes_fill = min(yes_m, extra + no_m)  # maximise matched volume
        no_fill = yes_fill - extra
        theta_yes = yes_fill / yes_m if yes_m > 0 else 0.0
        theta_no = no_fill / no_m if no_m > 0 else 0.0
        fills = {}
        for o in orders:
            if abs(o.bound - bound) <= _TIE:
                fills[o.order_id] = o.size * (theta_yes if o.side is Side.YES else theta_no)
            else:
                fills[o.order_id] = o.size if o.accepts(bound) else 0.0
        return _clearing(bound, d_star, fills, q_yes, q_no, b)

    raise AssertionError("no clearing price found: the demand/supply crossing must exist")  # pragma: no cover


def _clearing(p: float, d: float, fills: dict[int, float], q_yes: float, q_no: float, b: float) -> Clearing:
    side, amount = (Side.YES, d) if d >= 0 else (Side.NO, -d)
    lmsr = cost_at_price(price_yes(q_yes, q_no, b), b, side, amount) if amount > 0 else 0.0
    # The uniform price is the LMSR's average price for the imbalance actually traded.
    price = average_price(q_yes, q_no, b, d) if abs(d) > 1e-15 else p
    return Clearing(price_yes=price, net_yes=d, lmsr_cost=lmsr, fills=fills)


def cost_of_sets(c: Clearing, orders: Sequence[SealedOrder]) -> float:
    """Cash needed for the matched complete sets: one per filled NO share when D ≥ 0, else per YES share."""
    yes = sum(c.fills.get(o.order_id, 0.0) for o in orders if o.side is Side.YES)
    no = sum(c.fills.get(o.order_id, 0.0) for o in orders if o.side is Side.NO)
    return min(yes, no)


__all__ = ["SealedOrder", "Clearing", "clear_batch", "average_price", "cost_of_sets", "cost"]
