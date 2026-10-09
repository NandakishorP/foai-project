"""Fractional Kelly sizing for a binary contract (the utility-based decision, SPEC §6).

A YES share costs m and pays 1 if Y=1. To an agent with belief p > m, the Kelly
fraction of wealth to stake (maximising expected log wealth) is
f* = (p − m) / (1 − m). Symmetrically, when p < m, a NO share costs 1 − m and
f* = (m − p) / m. We bet a fraction k of Kelly ("fractional Kelly") to allow
for errors in the belief itself.
"""

from __future__ import annotations


def kelly_fraction(belief: float, price: float, k: float) -> float:
    """Signed fraction of bankroll to stake: positive on YES, negative on NO."""
    if belief > price:
        return k * (belief - price) / (1.0 - price)
    if belief < price:
        return -k * (price - belief) / price
    return 0.0


def kelly_target_net_yes(belief: float, price: float, k: float, bankroll: float) -> float:
    """Target net exposure in shares (YES − NO): the stake divided by the share's price."""
    f = kelly_fraction(belief, price, k)
    if f > 0:
        return f * bankroll / price
    if f < 0:
        return f * bankroll / (1.0 - price)
    return 0.0
