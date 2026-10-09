"""Shared value types: venues, sides, transactions, receipts, accounts."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Venue(str, Enum):
    MAIN = "main"  # the prediction market under study
    REF = "ref"  # smaller reference venue for the same event (DECISIONS D-005)


class Side(str, Enum):
    YES = "yes"
    NO = "no"

    @property
    def other(self) -> Side:
        return Side.NO if self is Side.YES else Side.YES


@dataclass(frozen=True)
class Trade:
    """Buy (shares > 0) or sell (shares < 0) outcome shares against a venue's LMSR.

    `limit_price` is a bound on the *average* price per share: the most a buyer
    will pay, or the least a seller will accept. The trade reverts entirely
    if it cannot be met (like an on-chain slippage check), so the order fills
    completely or not at all.
    """

    agent_id: str
    venue: Venue
    side: Side
    shares: float
    limit_price: float
    priority_fee: float = 0.0  # tip to the block builder (USDC), paid if the trade is included


@dataclass(frozen=True)
class Bundle:
    """Several trades executed back-to-back, all-or-nothing (used by arbitrageurs)."""

    agent_id: str
    trades: tuple[Trade, ...]


Tx = Trade | Bundle


@dataclass(frozen=True)
class Receipt:
    """Outcome of one trade. Prices are the venue's YES price around the trade."""

    trade: Trade
    ok: bool
    reason: str  # "" when ok, else why it reverted
    cost: float  # cash paid by the agent for shares (negative = cash received); 0 if reverted; excludes fees
    price_before: float
    price_after: float


@dataclass
class Account:
    """An agent's cash and outcome-share holdings on each venue."""

    cash: float
    shares: dict[tuple[Venue, Side], float] = field(default_factory=dict)

    def position(self, venue: Venue, side: Side) -> float:
        return self.shares.get((venue, side), 0.0)

    def net_yes(self, venue: Venue) -> float:
        """YES shares minus NO shares on a venue: the agent's directional exposure."""
        return self.position(venue, Side.YES) - self.position(venue, Side.NO)

    def copy(self) -> Account:
        return Account(cash=self.cash, shares=dict(self.shares))
