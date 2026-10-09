import numpy as np
import pytest

from tfs.core.config import SimConfig, replace_in
from tfs.core.information import draw_forecaster_traits
from tfs.core.rng import RngFactory
from tfs.simulation import ResearchMemory, decide_research, run_market, run_season


def _small(cfg: SimConfig) -> SimConfig:
    return replace_in(cfg, "market.ticks", 120)


def test_non_researchers_do_not_trade(base_config: SimConfig) -> None:
    cfg = _small(base_config)
    rngs = RngFactory(0)
    traits = draw_forecaster_traits(cfg, rngs)
    record = run_market(cfg, rngs, 0, traits, frozenset({0, 3}))
    forecasters = sorted(a for a, k in record.kinds.items() if k == "forecaster")
    assert forecasters == ["forecaster_0", "forecaster_3"]


def test_market_conserves_money(base_config: SimConfig) -> None:
    """All agents' PnL plus the market makers' PnL sums to zero: money is only moved, never created."""
    record = run_season(_small(base_config), 4).markets[0]
    assert sum(record.pnl.values()) + sum(record.mm_pnl.values()) == pytest.approx(0.0, abs=1e-6)


def test_season_is_deterministic(base_config: SimConfig) -> None:
    cfg = replace_in(_small(base_config), "season.n_markets", 2)
    a, b = run_season(cfg, 11), run_season(cfg, 11)
    for ma, mb in zip(a.markets, b.markets):
        np.testing.assert_array_equal(ma.price_main, mb.price_main)
        assert ma.pnl == mb.pnl


def _endogenous(cfg: SimConfig, cost: float) -> SimConfig:
    cfg = replace_in(cfg, "agents.forecasters.research.cost_median", cost)
    return replace_in(cfg, "agents.forecasters.research.mode", "endogenous")


def test_research_rule(base_config: SimConfig) -> None:
    cfg = replace_in(_endogenous(base_config, 1.0), "agents.forecasters.research.explore_prob", 0.0)
    rngs = RngFactory(0)
    traits = draw_forecaster_traits(cfg, rngs)
    memory = ResearchMemory(ema=[None] * len(traits), alpha=0.3)
    assert decide_research(cfg, traits, memory, rngs, 0) == frozenset(range(len(traits)))  # no experience
    memory.ema = [t.cost + 1.0 if t.index % 2 == 0 else t.cost - 1.0 for t in traits]  # type: ignore[operator]
    assert decide_research(cfg, traits, memory, rngs, 1) == frozenset(t.index for t in traits if t.index % 2 == 0)


def test_exploration_rate(base_config: SimConfig) -> None:
    cfg = replace_in(_endogenous(base_config, 1.0), "agents.forecasters.research.explore_prob", 0.2)
    rngs = RngFactory(0)
    traits = draw_forecaster_traits(cfg, rngs)
    memory = ResearchMemory(ema=[-1e9] * len(traits), alpha=0.3)  # nobody wants to research
    picks = [len(decide_research(cfg, traits, memory, rngs, m)) for m in range(500)]
    assert np.mean(picks) / len(traits) == pytest.approx(0.2, abs=0.03)


def test_memory_updates_only_for_researchers(base_config: SimConfig) -> None:
    cfg = replace_in(_small(_endogenous(base_config, 1e9)), "season.n_markets", 3)  # costs too high to continue
    cfg = replace_in(cfg, "agents.forecasters.research.explore_prob", 0.0)
    season = run_season(cfg, 2)
    assert season.participation()[0] == 1.0  # optimistic start
    assert season.participation()[1:] == [0.0, 0.0]


def test_ema_update() -> None:
    m = ResearchMemory(ema=[None], alpha=0.5)
    m.update(0, 4.0)
    m.update(0, 0.0)
    assert m.ema[0] == pytest.approx(2.0)
