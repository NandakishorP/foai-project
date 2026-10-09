import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tfs.core.types import Side
from tfs.market.lmsr import (
    LmsrMarket,
    max_market_maker_loss,
    price_yes,
    trade_cost,
    yes_shares_to_move_price,
)

liquidity = st.floats(min_value=1.0, max_value=1000.0)
quantity = st.floats(min_value=-5000.0, max_value=5000.0)
size = st.floats(min_value=0.01, max_value=500.0)
prob = st.floats(min_value=0.01, max_value=0.99)


@given(q_yes=quantity, q_no=quantity, b=liquidity)
def test_prices_are_probabilities(q_yes: float, q_no: float, b: float) -> None:
    p = price_yes(q_yes, q_no, b)
    assert 0.0 <= p <= 1.0
    assert price_yes(q_no, q_yes, b) == pytest.approx(1.0 - p, abs=1e-12)


@given(q_yes=quantity, q_no=quantity, b=liquidity, shares=size, side=st.sampled_from(list(Side)))
def test_buy_then_sell_costs_nothing(q_yes: float, q_no: float, b: float, shares: float, side: Side) -> None:
    m = LmsrMarket(b=b, q_yes=q_yes, q_no=q_no)
    paid = m.execute(side, shares)
    received = -m.execute(side, -shares)
    assert paid == pytest.approx(received, rel=1e-9, abs=1e-6)


@given(b=liquidity, a=size, c=size)
def test_cost_is_path_independent(b: float, a: float, c: float) -> None:
    in_two_steps = trade_cost(0, 0, b, Side.YES, a) + trade_cost(a, 0, b, Side.YES, c)
    assert in_two_steps == pytest.approx(trade_cost(0, 0, b, Side.YES, a + c), rel=1e-9, abs=1e-9)


@given(b=liquidity, p_from=prob, p_to=prob)
def test_move_price_closed_form(b: float, p_from: float, p_to: float) -> None:
    m = LmsrMarket(b=b)
    m.execute(Side.YES, yes_shares_to_move_price(0.5, p_from, b))
    x = yes_shares_to_move_price(p_from, p_to, b)
    if x >= 0:
        m.execute(Side.YES, x)
    else:
        m.execute(Side.NO, -x)  # buying NO lowers the YES price
    assert m.price() == pytest.approx(p_to, abs=1e-9)


@given(
    b=liquidity,
    trades=st.lists(st.tuples(st.sampled_from(list(Side)), size), min_size=1, max_size=30),
    y=st.sampled_from([0, 1]),
)
def test_market_maker_loss_is_bounded(b: float, trades: list[tuple[Side, float]], y: int) -> None:
    m = LmsrMarket(b=b)
    for side, shares in trades:
        m.execute(side, shares)
    mm_pnl = m.collateral - m.payout(y)
    assert mm_pnl >= -max_market_maker_loss(b) - 1e-6


@settings(max_examples=20)
@given(b=liquidity)
def test_extreme_quantities_are_stable(b: float) -> None:
    q = 1e6 * b  # exp(q/b) would overflow without log-sum-exp
    assert price_yes(q, 0.0, b) == 1.0
    assert math.isfinite(trade_cost(q, 0.0, b, Side.YES, 1.0))
    assert trade_cost(q, 0.0, b, Side.YES, 1.0) == pytest.approx(1.0)  # YES is ~certain: costs ~1


def test_buying_raises_own_price() -> None:
    m = LmsrMarket(b=100.0)
    p0 = m.price()
    m.execute(Side.YES, 10.0)
    assert m.price() > p0
    m.execute(Side.NO, 30.0)
    assert m.price() < p0
