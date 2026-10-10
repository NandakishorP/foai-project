"""How much of its Kelly shortfall an informed trader sends this block (E4, SPEC §6.1).

`KellyTrader` decides *whether* and *in which direction* to trade, and the limit price.
A slice rule decides only the *size* of this block's order. Each rule is a small class
with one method, so the E4 strategies can be compared with everything else held equal.

| rule            | size this block                                                     |
|-----------------|---------------------------------------------------------------------|
| capped          | min(shortfall, max_order, push cap): the Phase 1–3a rule (default)  |
| naive           | min(shortfall, push cap): everything at once                        |
| twap            | shortfall / n, at most the push cap                                 |
| random          | a random fraction from the search's action set {0, 1/8, 1/4, 1/2, 1}|
| expectiminimax  | the first move of the order-splitting game (tfs.search)              |
| crowd_expectiminimax | the same, with the same-signal crowd in the game (EXPLORATORY X-5) |

The push cap is the size that moves the price exactly to the trader's belief; no rule
ever exceeds it, so no trade is made at a loss under the trader's own belief.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np

from tfs.agents.beliefs import clipped_logit
from tfs.core.config import ExecutionConfig
from tfs.search.order_splitting import SLICE_FRACTIONS, SplittingPolicy


@dataclass(frozen=True)
class SliceInput:
    belief: float  # the trader's probability of YES
    price: float  # the current YES price
    shortfall: float  # shares still needed to reach the Kelly target (> 0)
    push_cap: float  # shares that would move the price exactly to the belief
    fresh: bool  # the belief changed this tick (new information arrived)


class SliceRule(Protocol):
    def size(self, x: SliceInput) -> float: ...


@dataclass(frozen=True)
class Capped:
    max_order: float

    def size(self, x: SliceInput) -> float:
        return min(x.shortfall, self.max_order, x.push_cap)


class Naive:
    def size(self, x: SliceInput) -> float:
        return min(x.shortfall, x.push_cap)


@dataclass(frozen=True)
class Twap:
    slices: int

    def size(self, x: SliceInput) -> float:
        return min(x.shortfall / self.slices, x.push_cap)


@dataclass
class RandomSlice:
    rng: np.random.Generator  # the trader's own stream, so other agents' draws are unaffected

    def size(self, x: SliceInput) -> float:
        fraction = SLICE_FRACTIONS[int(self.rng.integers(len(SLICE_FRACTIONS)))]
        return min(fraction * x.shortfall, x.push_cap)


@dataclass
class SearchSlice:
    policy: SplittingPolicy  # shared by the season's forecasters; solved states are reused

    def size(self, x: SliceInput) -> float:
        q = self.policy.slice(clipped_logit(x.belief), clipped_logit(x.price), x.shortfall, x.fresh)
        return min(q, x.push_cap)


def make_slice_rule(ex: ExecutionConfig, max_order: float, index: int, rng: np.random.Generator,
                    policy: SplittingPolicy | None) -> SliceRule:
    """The rule forecaster `index` uses. Only the first `ex.users` forecasters use `ex.rule` (all if None)."""
    rule = ex.rule if ex.users is None or index < ex.users else "capped"
    if rule == "capped":
        return Capped(max_order)
    if rule == "naive":
        return Naive()
    if rule == "twap":
        return Twap(ex.twap_slices)
    if rule == "random":
        return RandomSlice(rng)
    assert policy is not None, "the search rules need the season's SplittingPolicy"
    return SearchSlice(policy)
