"""E5 whale: budget respected, backs the wrong outcome, and a budget-0 whale leaves the world untouched."""

from pathlib import Path

import numpy as np

from tfs.core.config import load_config, replace_in
from tfs.simulation import run_season

BASE = replace_in(load_config(Path("sim/experiments/configs/base.yaml")), "information.shocks", ())


def whale(budget: float, count: int = 1):
    return replace_in(replace_in(BASE, "agents.whale.count", count), "agents.whale.budget", budget)


def test_a_budget_zero_whale_changes_nothing() -> None:
    """The paired design of E5: the twin with a budget-0 whale is the market without a whale, exactly."""
    for seed in range(3):
        a, b = run_season(whale(0.0), seed).markets[0], run_season(whale(0.0, count=0), seed).markets[0]
        assert np.array_equal(a.price_main, b.price_main)


def test_the_whale_never_spends_more_than_its_budget() -> None:
    for seed in range(5):
        m = run_season(whale(50.0), seed).markets[0]
        assert m.pnl["whale_0"] >= -50.0 - 1e-6  # it holds shares to resolution: at worst it loses what it spent


def test_the_whale_pushes_against_the_outcome() -> None:
    pushes = []
    for seed in range(20):
        with_whale, without = run_season(whale(800.0), seed).markets[0], run_season(whale(0.0), seed).markets[0]
        truth = 1 if with_whale.y == 1 else -1
        pushes.append(truth * (with_whale.price_main[100:140] - without.price_main[100:140]).mean())
    assert np.mean(pushes) < -0.05  # the price of the true outcome is held down
