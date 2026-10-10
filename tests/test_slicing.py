"""Slice rules (E4): caps hold, the random rule has its own stream, the search rule is deterministic."""

from pathlib import Path

import numpy as np
import pytest

from tfs.agents.slicing import Capped, Naive, RandomSlice, SearchSlice, SliceInput, Twap, make_slice_rule
from tfs.core.config import load_config, replace_in
from tfs.simulation import run_season, season_policy

BASE = load_config(Path("sim/experiments/configs/base.yaml"))
SHORT = replace_in(replace_in(BASE, "information.shocks", ()), "market.ticks", 60)


def with_rule(rule: str, users: int | None = None):
    cfg = replace_in(SHORT, "agents.forecasters.execution.rule", rule)
    return replace_in(cfg, "agents.forecasters.execution.users", users)


def test_no_rule_exceeds_the_shortfall_or_the_push_cap() -> None:
    policy = season_policy(with_rule("expectiminimax"))
    rules = [Capped(20.0), Naive(), Twap(5), RandomSlice(np.random.default_rng(0)), SearchSlice(policy)]
    rng = np.random.default_rng(1)
    for _ in range(100):
        price = rng.uniform(0.1, 0.9)
        belief = min(0.99, price + rng.uniform(0.01, 0.3))
        push_cap = 100.0 * (np.log(belief / (1 - belief)) - np.log(price / (1 - price)))
        x = SliceInput(belief, price, rng.uniform(0.5, 150.0), push_cap, fresh=bool(rng.integers(2)))
        for rule in rules:
            assert 0.0 <= rule.size(x) <= min(x.shortfall, x.push_cap) + 1e-9, rule


def test_capped_is_the_phase_1_rule() -> None:
    x = SliceInput(0.7, 0.5, 35.0, 84.7, fresh=False)
    assert Capped(20.0).size(x) == min(35.0, 20.0, 84.7)


def test_only_the_first_users_take_the_rule() -> None:
    ex = with_rule("naive", users=1).agents.forecasters.execution
    rng = np.random.default_rng(0)
    assert isinstance(make_slice_rule(ex, 20.0, 0, rng, None), Naive)
    assert isinstance(make_slice_rule(ex, 20.0, 1, rng, None), Capped)


def test_rules_leave_the_world_and_the_noise_traders_untouched() -> None:
    """Changing how forecasters slice must not change signals or noise-trader draws (paired design)."""
    a = run_season(with_rule("capped"), seed=3).markets[0]
    b = run_season(with_rule("random"), seed=3).markets[0]
    assert np.array_equal(a.p_full, b.p_full)
    assert a.attempts_by_kind["noise"] == b.attempts_by_kind["noise"]


@pytest.mark.parametrize("rule", ["naive", "twap", "random", "expectiminimax"])
def test_each_rule_runs_and_is_deterministic(rule: str) -> None:
    cfg = replace_in(with_rule(rule), "season.n_markets", 2)
    first, second = run_season(cfg, seed=5), run_season(cfg, seed=5)
    for m1, m2 in zip(first.markets, second.markets):
        assert np.array_equal(m1.price_main, m2.price_main)
        assert m1.pnl == m2.pnl
    assert first.markets[0].attempts_by_kind.get("forecaster", 0) > 0
