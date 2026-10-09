"""Turning a desired change in exposure into a concrete trade.

Exposure to YES can be increased in two ways: buy YES, or sell NO shares
already held. Both move the YES price up by the same amount in an LMSR. We sell
the opposite side first, so an agent never holds YES and NO at once, which
would just be locked-up collateral.
"""

from __future__ import annotations

from tfs.core.types import Account, Side, Trade, Venue


def exposure_trade(
    agent_id: str,
    venue: Venue,
    account: Account,
    direction: int,
    size: float,
    buy_limit: float,
    sell_limit: float,
) -> Trade:
    """A trade that moves net YES exposure by `size` shares in `direction` (+1 more YES, −1 more NO).

    `buy_limit` is the max average price of the side being bought; `sell_limit`
    is the min average price of the side being sold.
    """
    favoured = Side.YES if direction > 0 else Side.NO
    opposite = favoured.other
    held_opposite = account.position(venue, opposite)
    if held_opposite > 0:
        return Trade(agent_id, venue, opposite, -min(size, held_opposite), sell_limit)
    return Trade(agent_id, venue, favoured, size, buy_limit)
