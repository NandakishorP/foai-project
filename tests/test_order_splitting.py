"""The order-splitting game: closed forms match the predator, values respect bounds, pruning is exact."""

import dataclasses
import math
from pathlib import Path

import numpy as np
import pytest

from tfs.agents.predator import Predator, PredatorMemory, front_run_ev
from tfs.core.config import load_config
from tfs.core.types import Side, Trade, Venue
from tfs.market.lmsr import affordable_shares, cost_at_price, highest_logodds_to_fill, sigmoid
from tfs.search.expectiminimax import Node, Options, Searcher, expectiminimax
from tfs.search.order_splitting import OrderSplittingGame, SplittingPolicy, split_params

BASE = load_config(Path("sim/experiments/configs/base.yaml"))
PARAMS = dataclasses.replace(split_params(BASE), max_depth=2)


def test_closed_form_front_run_cap_matches_the_predators_bisection() -> None:
    predator = Predator("predator_0", 100.0, BASE.agents.predators, PredatorMemory(), market_ticks=200)
    rng = np.random.default_rng(0)
    for _ in range(200):
        shares, limit, slot = rng.uniform(1, 80), rng.uniform(0.2, 0.95), rng.uniform(-2, 1)
        victim = Trade("forecaster_0", Venue.MAIN, Side.YES, shares, limit)
        bisection = predator._largest_front_run(victim, 1, slot)
        closed = max(0.0, 100.0 * (highest_logodds_to_fill(shares, limit, 100.0) - slot))
        assert closed == pytest.approx(bisection, abs=1e-6)


def test_affordable_shares_inverts_the_cost() -> None:
    for price in (0.1, 0.5, 0.9):
        for budget in (1.0, 50.0, 200.0):
            assert cost_at_price(price, 100.0, Side.YES, affordable_shares(price, 100.0, budget)) == pytest.approx(budget)


def _roots(n: int, seed: int = 0):
    rng = np.random.default_rng(seed)
    game = OrderSplittingGame(PARAMS)
    for _ in range(n):
        price = rng.uniform(-1.5, 1.5)
        yield game, game.root(price + rng.uniform(0.05, 1.2), price, rng.uniform(1, 120))


def test_no_edge_or_nothing_to_buy_is_terminal() -> None:
    game = OrderSplittingGame(PARAMS)
    assert game.node(game.root(0.3, 0.3, 50.0)) is Node.TERMINAL
    assert game.node(game.root(0.8, 0.3, 0.1)) is Node.TERMINAL


def test_values_and_heuristic_stay_within_bounds() -> None:
    for game, root in _roots(40):
        lo, hi = game.bounds(root)
        assert lo <= game.heuristic(root) <= hi + 1e-12
        assert lo - 1e-12 <= expectiminimax(game, root, 2) <= hi + 1e-12


def test_pruned_search_returns_the_plain_value_on_the_real_game() -> None:
    for game, root in _roots(30, seed=1):
        expected = expectiminimax(game, root, 2)
        for options in (Options(star1=False, ordering=False, transposition=False), Options()):
            assert Searcher(game, options).value(root, 2) == pytest.approx(expected, abs=1e-9)


def test_without_a_predator_and_with_decaying_edge_send_everything_now() -> None:
    """If no front-run can ever pay, waiting only lets others take the edge: the best slice is the largest."""
    params = dataclasses.replace(PARAMS, predator_min_profit=math.inf, kappa=0.5)
    game = OrderSplittingGame(params)
    root = game.root(0.8, 0.0, 30.0)
    q, _ = Searcher(game).best_action(root, 2)
    assert q == pytest.approx(min(root.remaining, game.push_cap(root)))


def test_a_no_edge_mirrors_a_yes_edge() -> None:
    policy = SplittingPolicy(OrderSplittingGame(PARAMS), depth=2)
    assert policy.slice(-0.6, 0.1, 40.0) == pytest.approx(policy.slice(0.6, -0.1, 40.0))


def test_policy_reuses_solved_states_and_respects_the_push_cap() -> None:
    policy = SplittingPolicy(OrderSplittingGame(PARAMS), depth=2)
    first = policy.slice(0.9, 0.0, 60.0)
    solved = policy.roots_solved
    assert policy.slice(0.9, 0.0, 60.0) == first and policy.roots_solved == solved
    assert 0.0 <= first <= 100.0 * 0.9 + 1e-9
    assert policy.slice(0.2, 0.2, 60.0) == 0.0


def test_the_predator_only_front_runs_when_it_expects_a_profit() -> None:
    game = OrderSplittingGame(PARAMS)
    root = game.root(0.8, 0.0, 40.0)
    for q in game.actions(root, ordered=False):
        _, at_min = game.result(root, q)
        for f in game.actions(at_min, ordered=False):
            if f > 0:
                drift = PARAMS.predator_p_informed * PARAMS.predator_drift
                ev = front_run_ev(f, PARAMS.b, Side.YES, 1, at_min.price, q, 1.0, drift, False, 0.0)
                assert ev * (1 - PARAMS.bid_share) >= PARAMS.predator_min_profit
                assert cost_at_price(sigmoid(at_min.price + f / PARAMS.b), PARAMS.b, Side.YES, q) <= q * sigmoid(
                    at_min.belief) + 1e-9  # the slice still fills after the front-run


@pytest.mark.slow  # plain expectiminimax at depth 5: about a minute
def test_search_benchmark_rows_agree_with_plain_search() -> None:
    from tfs.experiments.search_bench import benchmark

    game = OrderSplittingGame(PARAMS)
    states = [game.root(0.9, 0.2, 60.0), game.root(-0.4, 0.3, 25.0), game.root(1.5, 1.0, 90.0)]
    rows = benchmark(BASE, states, plain_depth5_states=1)
    assert all(r.max_value_error < 1e-9 for r in rows)
    plain = {r.depth: r.mean_nodes for r in rows if r.variant == "plain" and r.depth < 5}
    full = {r.depth: r.mean_nodes for r in rows if r.variant == "+ transposition table"}
    assert all(full[d] <= plain[d] for d in plain)


# --------------------------------------------------------------------------- X-5: the crowd-aware game (EXPLORATORY)


def test_a_crowd_that_always_takes_the_whole_gap_leaves_nothing() -> None:
    game = OrderSplittingGame(dataclasses.replace(PARAMS, crowd_ahead=(1.0,)))
    root = game.root(0.8, 0.0, 40.0)
    assert expectiminimax(game, root, 2) == pytest.approx(0.0, abs=1e-9)


def test_a_crowd_that_never_trades_ahead_changes_nothing_but_the_check() -> None:
    plain = OrderSplittingGame(PARAMS)
    crowd = OrderSplittingGame(dataclasses.replace(PARAMS, crowd_ahead=(0.0,)))
    for _, root in _roots(10, seed=3):
        assert expectiminimax(crowd, root, 2) == pytest.approx(expectiminimax(plain, root, 2), abs=1e-9)


def test_pruning_is_exact_on_the_crowd_game() -> None:
    game = OrderSplittingGame(dataclasses.replace(PARAMS, crowd_ahead=(0.0, 0.2, 0.5, 0.8, 1.0)))
    for _, root in _roots(20, seed=4):
        expected = expectiminimax(game, root, 2)
        assert Searcher(game, Options()).value(root, 2) == pytest.approx(expected, abs=1e-9)
