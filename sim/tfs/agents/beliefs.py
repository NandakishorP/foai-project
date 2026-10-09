"""Belief states for informed agents: two ways to combine signals with the market price.

Both are Bayesian log-odds updates; they differ in what they treat as the prior
(DECISIONS D-013).

- `OwnSignalsBelief` (SPEC default): log-odds = prior + every signal the agent
  has seen. The market price is ignored. Simple and fully Bayesian about the
  agent's own information. However, Kelly traders then push the price toward
  a wealth-weighted *average* of their beliefs, not the pooled posterior.
- `PriceAnchoredBelief`: the agent treats the market price as the consensus of
  everyone else's information and adds only what it knows that the price does
  not yet reflect: log-odds = logit(price) + r, where r is the agent's
  *unpriced* information. r grows with each new signal and shrinks by the
  log-odds price impact of the agent's own fills. Each signal therefore enters
  the price roughly once, so information pools across traders. The caveat:
  price moves caused by noise traders are also read as information.
"""

from __future__ import annotations

import math
from typing import Protocol

from tfs.core.config import BeliefModel
from tfs.core.types import Receipt
from tfs.market.lmsr import logit, sigmoid

# Prices are clipped away from 0 and 1 before taking logits.
_PRICE_CLIP = 1e-9


def clipped_logit(p: float) -> float:
    return logit(min(max(p, _PRICE_CLIP), 1.0 - _PRICE_CLIP))


class Belief(Protocol):
    def observe(self, llr: float) -> None:
        """Incorporate new evidence, given as a log-likelihood ratio for Y=1."""

    def on_own_fill(self, receipt: Receipt) -> None:
        """Learn from one of the agent's own executed trades."""

    def probability(self, price: float) -> float:
        """Subjective P(Y=1) given the current market price."""


class OwnSignalsBelief:
    """log-odds = prior + Σ observed LLRs; independent of the market price."""

    def __init__(self, prior_logodds: float) -> None:
        self.logodds = prior_logodds

    def observe(self, llr: float) -> None:
        self.logodds += llr

    def on_own_fill(self, receipt: Receipt) -> None:
        pass  # the agent's own trades carry no new information about Y

    def probability(self, price: float) -> float:
        return sigmoid(self.logodds)


class PriceAnchoredBelief:
    """log-odds = logit(price) + r, with r = information not yet pushed into the price."""

    def __init__(self) -> None:
        self.residual = 0.0

    def observe(self, llr: float) -> None:
        self.residual += llr

    def on_own_fill(self, receipt: Receipt) -> None:
        """The agent's own price impact is its information entering the price; remove it from r.

        r shrinks toward zero but never changes sign: overshooting the target
        does not create information in the opposite direction.
        """
        if not receipt.ok or self.residual == 0.0:
            return
        impact = clipped_logit(receipt.price_after) - clipped_logit(receipt.price_before)
        remaining = self.residual - impact
        if math.copysign(1.0, remaining) != math.copysign(1.0, self.residual):
            remaining = 0.0
        self.residual = remaining

    def probability(self, price: float) -> float:
        return sigmoid(clipped_logit(price) + self.residual)


def make_belief(model: BeliefModel, prior_logodds: float) -> Belief:
    if model == "own_signals":
        return OwnSignalsBelief(prior_logodds)
    if model == "price_anchored":
        return PriceAnchoredBelief()
    raise ValueError(f"unknown belief model {model!r}")
