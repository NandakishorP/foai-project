"""Uniform-price batch clearing with a pro-rata margin (D-046)."""

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tfs.core.types import Side
from tfs.market.batch import SealedOrder, average_price, clear_batch, cost_of_sets
from tfs.market.lmsr import price_yes

B = 100.0

order_st = st.tuples(st.booleans(), st.floats(0.5, 60.0), st.floats(0.05, 0.95))
book_st = st.lists(order_st, min_size=1, max_size=12)
state_st = st.tuples(st.floats(-150, 150), st.floats(-150, 150))


def _orders(book) -> list[SealedOrder]:
    return [SealedOrder(i, f"a{i}", Side.YES if yes else Side.NO, size, limit) for i, (yes, size, limit) in enumerate(book)]


@settings(max_examples=300, deadline=None)
@given(book=book_st, state=state_st)
def test_budget_balance(book, state) -> None:
    """Payments by buyers exactly cover the complete sets plus the LMSR cost of the imbalance."""
    q_yes, q_no = max(state[0], 0.0), max(state[1], 0.0)
    orders = _orders(book)
    c = clear_batch(orders, q_yes, q_no, B)
    paid = sum(c.paid(o) for o in orders)
    assert paid == pytest.approx(cost_of_sets(c, orders) + c.lmsr_cost, abs=1e-7)


@settings(max_examples=300, deadline=None)
@given(book=book_st, state=state_st)
def test_no_fill_outside_a_limit_and_fills_bounded(book, state) -> None:
    q_yes, q_no = max(state[0], 0.0), max(state[1], 0.0)
    orders = _orders(book)
    c = clear_batch(orders, q_yes, q_no, B)
    for o in orders:
        f = c.fills[o.order_id]
        assert -1e-12 <= f <= o.size + 1e-9
        if f > 1e-9:
            unit = c.price_yes if o.side is Side.YES else 1 - c.price_yes
            assert unit <= o.limit + 1e-7, (o, c.price_yes)


@settings(max_examples=300, deadline=None)
@given(book=book_st, state=state_st)
def test_price_is_the_fixed_point(book, state) -> None:
    """p* equals the LMSR average price of the net imbalance actually filled."""
    q_yes, q_no = max(state[0], 0.0), max(state[1], 0.0)
    orders = _orders(book)
    c = clear_batch(orders, q_yes, q_no, B)
    net = sum(c.fills[o.order_id] * (1 if o.side is Side.YES else -1) for o in orders)
    assert net == pytest.approx(c.net_yes, abs=1e-7)
    assert c.price_yes == pytest.approx(average_price(q_yes, q_no, B, c.net_yes), abs=1e-9)


@settings(max_examples=200, deadline=None)
@given(book=book_st)
def test_no_willing_order_left_unfilled_when_price_strictly_inside(book) -> None:
    """Any order whose bound is strictly better than p* fills fully (only the margin is rationed)."""
    orders = _orders(book)
    c = clear_batch(orders, 0.0, 0.0, B)
    for o in orders:
        strictly = (c.price_yes < o.bound - 1e-6) if o.side is Side.YES else (c.price_yes > o.bound + 1e-6)
        if strictly:
            assert c.fills[o.order_id] == pytest.approx(o.size, rel=1e-9)


def test_identical_researchers_share_the_fill_pro_rata() -> None:
    """Ten identical YES orders, each sized to push the price to 0.6 alone: they overshoot together.

    D-004's drop rule would have cleared nothing. Here the clearing price is exactly the shared limit,
    and each order gets the same fraction.
    """
    size = B * (np.log(0.6 / 0.4))  # shares that alone move 0.5 -> 0.6
    orders = [SealedOrder(i, f"r{i}", Side.YES, size, 0.6) for i in range(10)]
    c = clear_batch(orders, 0.0, 0.0, B)
    assert c.price_yes == pytest.approx(0.6, abs=1e-9)
    fills = [c.fills[i] for i in range(10)]
    assert all(f == pytest.approx(fills[0]) for f in fills)
    assert 0 < fills[0] < size
    assert average_price(0.0, 0.0, B, sum(fills)) == pytest.approx(0.6, abs=1e-9)


def test_offsetting_orders_trade_at_the_marginal_price() -> None:
    orders = [SealedOrder(0, "y", Side.YES, 10.0, 0.9), SealedOrder(1, "n", Side.NO, 10.0, 0.9)]
    c = clear_batch(orders, 0.0, 0.0, B)
    assert c.net_yes == pytest.approx(0.0, abs=1e-9)
    assert c.price_yes == pytest.approx(0.5)
    assert c.fills == {0: 10.0, 1: 10.0}
    assert c.lmsr_cost == 0.0


def test_nobody_willing_means_no_trade() -> None:
    orders = [SealedOrder(0, "y", Side.YES, 10.0, 0.3)]  # will not pay 0.5
    c = clear_batch(orders, 0.0, 0.0, B)
    assert c.fills[0] == 0.0 and c.net_yes == 0.0 and c.price_yes == pytest.approx(price_yes(0, 0, B))


@settings(max_examples=150, deadline=None)
@given(book=book_st)
def test_matches_a_brute_force_grid_solver(book) -> None:
    """On a fine price grid, the price minimising |avgprice(D_full(p)) − p| over the step function is p*."""
    orders = _orders(book)
    c = clear_batch(orders, 0.0, 0.0, B)
    grid = np.linspace(1e-4, 1 - 1e-4, 4001)

    def gap(p: float) -> float:
        d = sum(o.size * (1 if o.side is Side.YES else -1) for o in orders if o.accepts(p))
        return average_price(0.0, 0.0, B, d) - p

    gaps = np.array([gap(p) for p in grid])
    # the step function crosses zero once: find where the sign changes
    sign_change = np.flatnonzero(np.diff(np.sign(gaps)) != 0)
    if sign_change.size:
        crossing = grid[sign_change[0]]
        assert abs(crossing - c.price_yes) < 3e-4, (crossing, c.price_yes)


# --------------------------------------------------------------------------- X-4: marginal clearing (EXPLORATORY)


@settings(max_examples=300, deadline=None)
@given(book=book_st, state=state_st)
def test_marginal_rule_ends_the_market_at_the_clearing_price(book, state) -> None:
    """Under X-4 the LMSR's price after the batch equals the uniform price: no filled limit is overshot."""
    q_yes, q_no = max(state[0], 0.0), max(state[1], 0.0)
    orders = _orders(book)
    c = clear_batch(orders, q_yes, q_no, B, rule="marginal")
    after = price_yes(q_yes + max(c.net_yes, 0.0), q_no + max(-c.net_yes, 0.0), B)
    assert after == pytest.approx(c.price_yes, abs=1e-9)
    for o in orders:
        if c.fills[o.order_id] > 1e-9:
            assert o.accepts(c.price_yes)


@settings(max_examples=300, deadline=None)
@given(book=book_st, state=state_st)
def test_marginal_rule_payments_cover_cost_sets_and_a_nonnegative_surplus(book, state) -> None:
    q_yes, q_no = max(state[0], 0.0), max(state[1], 0.0)
    orders = _orders(book)
    c = clear_batch(orders, q_yes, q_no, B, rule="marginal")
    paid = sum(c.paid(o) for o in orders)
    assert c.surplus >= -1e-9
    assert paid == pytest.approx(cost_of_sets(c, orders) + c.lmsr_cost + c.surplus, abs=1e-7)


def test_identical_researchers_no_longer_overshoot_their_shared_limit() -> None:
    """Five identical YES orders at 0.6 from 0.5: the average rule ends above 0.6, the marginal rule at 0.6."""
    orders = [SealedOrder(i, f"r{i}", Side.YES, 40.0, 0.6) for i in range(5)]
    avg = clear_batch(orders, 0.0, 0.0, B, rule="average")
    marg = clear_batch(orders, 0.0, 0.0, B, rule="marginal")
    assert price_yes(avg.net_yes, 0.0, B) > 0.65  # the marginal price ends well past every limit
    assert price_yes(marg.net_yes, 0.0, B) == pytest.approx(0.6, abs=1e-9)
    assert marg.net_yes < avg.net_yes and marg.surplus > 0
