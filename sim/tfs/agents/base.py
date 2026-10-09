"""Agent interface: perceive an observation, then act by returning transactions (SPEC §6).

Each agent's class docstring gives its PEAS description:
Performance measure, Environment, Actuators, Sensors.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar

from tfs.core.types import Account, Receipt, Tx, Venue
from tfs.mempool.mempool import PendingTx


@dataclass(frozen=True)
class Observation:
    """Everything an agent may perceive at one tick. Built by the simulation, which enforces visibility."""

    tick: int
    prices: Mapping[Venue, float]  # YES price of each venue after the previous block
    public_llr: float  # LLR of public news that became visible to this agent this tick (after its latency)
    private_llr: float  # LLR of this agent's own private signals arriving this tick
    account: Account  # a copy of the agent's own account
    receipts: tuple[Receipt, ...]  # the agent's own transaction results from the previous block
    mempool: tuple[PendingTx, ...] = ()  # pending transactions this agent can read (predators only)
    last_block: tuple[Receipt, ...] = ()  # every receipt of the previous block, in execution order (public chain data)


class Agent(ABC):
    """Base class for every market participant."""

    kind: ClassVar[str]  # label used to group results (e.g. PnL by agent type)

    def __init__(
        self,
        agent_id: str,
        bankroll: float,
        public_latency: int | None = None,
        private_source: int | None = None,
    ) -> None:
        self.agent_id = agent_id
        self.bankroll = bankroll  # starting cash in this market
        self.public_latency = public_latency  # None: does not follow public news
        self.private_source = private_source  # forecaster index whose private signals it receives

    @abstractmethod
    def perceive(self, obs: Observation) -> None:
        """Update internal state from the observation."""

    @abstractmethod
    def act(self) -> list[Tx]:
        """Return the transactions to send this tick (possibly none)."""
