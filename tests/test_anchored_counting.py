"""Does a price-anchored trader count each piece of evidence exactly once?

An anchored agent believes logit(price) + r, where r is evidence it has not yet
pushed into the price. If it re-added cumulative evidence on every tick, a lone
agent would push the price further and further. These tests run a single agent
against the engine with nobody else trading: the price's log-odds must end at
exactly prior + Σ evidence.
"""

import pytest

from tfs.agents.base import Observation
from tfs.agents.beliefs import PriceAnchoredBelief
from tfs.agents.forecaster import InformedForecaster
from tfs.core.types import Receipt, Venue
from tfs.engines.fast import FastEngine
from tfs.market.lmsr import logit

B = 100.0


def _run(evidence: dict[int, float], ticks: int, max_order: float) -> list[float]:
    """Run one anchored forecaster alone; return the price log-odds after every block."""
    agent = InformedForecaster(
        index=0, liquidity=B, belief=PriceAnchoredBelief(), kelly_fraction=1.0,
        bankroll=1e9, max_order=max_order, min_order=1e-9, public_latency=0,
    )
    engine = FastEngine({Venue.MAIN: B, Venue.REF: B}, {agent.agent_id: 1e9})
    receipts: tuple[Receipt, ...] = ()
    path = []
    for tick in range(ticks):
        agent.perceive(Observation(tick, engine.prices(), 0.0, evidence.get(tick, 0.0),
                                   engine.balances()[agent.agent_id], receipts))
        receipts = tuple(engine.build_block(agent.act()))
        path.append(logit(engine.prices()[Venue.MAIN]))
    return path


def test_each_signal_is_priced_once_and_not_again() -> None:
    path = _run({0: 0.8, 5: -0.3, 6: 0.5}, ticks=12, max_order=1e9)
    assert path[0] == pytest.approx(0.8)
    assert path[1:5] == pytest.approx([0.8] * 4)  # no new evidence: no further pushing
    assert path[5] == pytest.approx(0.5)
    assert path[-1] == pytest.approx(1.0)  # = 0.8 - 0.3 + 0.5, not more


def test_capped_orders_carry_only_the_unpriced_remainder() -> None:
    """Orders capped at 20 shares (0.2 log-odds each) spread one signal over several ticks without overshooting."""
    path = _run({0: 1.0}, ticks=10, max_order=20.0)
    assert path[0] == pytest.approx(0.2)
    assert path[3] == pytest.approx(0.8)
    assert path[-1] == pytest.approx(1.0)
