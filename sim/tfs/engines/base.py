"""The `Engine` interface shared by FastEngine (pure Python) and EvmEngine (Anvil, Phase 2b).

Agents and the experiment lab only talk to this interface, so the same scenario
can run on either engine and a differential test can check that they agree.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass

from tfs.core.types import Account, Receipt, Tx, Venue


@dataclass(frozen=True)
class VenueState:
    b: float
    q_yes: float
    q_no: float
    collateral: float
    price: float


@dataclass(frozen=True)
class EngineState:
    venues: dict[Venue, VenueState]
    block: int  # number of blocks built so far
    resolved_outcome: int | None


class Engine(ABC):
    """Executes transactions against the markets and keeps balances."""

    @abstractmethod
    def submit(self, tx: Tx) -> list[Receipt]:
        """Execute one transaction on its own, as a single-transaction block."""

    @abstractmethod
    def build_block(self, ordered_txs: Sequence[Tx]) -> list[Receipt]:
        """Execute transactions as one block, in exactly the given order.

        Ordering is decided outside the engine (by the builder) because
        ordering is what front-running exploits.
        """

    @abstractmethod
    def state(self) -> EngineState: ...

    @abstractmethod
    def prices(self) -> dict[Venue, float]:
        """Current YES price of each venue."""

    @abstractmethod
    def balances(self) -> dict[str, Account]:
        """Copies of every agent's account."""

    @abstractmethod
    def resolve(self, y: int) -> None:
        """Settle every venue on outcome `y`: winning shares pay 1, losing shares pay 0."""
