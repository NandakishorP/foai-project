"""FastEngine sealed-batch settlement: escrow, uniform-price fills, refunds, slashing, merging (D-046)."""

import pytest

from tfs.core.types import Side, Venue
from tfs.engines.fast import BUILDER_ID, SLASHED_ID, FastEngine
from tfs.market.batch import SealedOrder
from tfs.market.lmsr import max_market_maker_loss

LIQ = {Venue.MAIN: 100.0, Venue.REF: 30.0}


def _total(e: FastEngine) -> float:
    return sum(a.cash for a in e.balances().values()) + sum(v.collateral for v in e.state().venues.values())


def _engine() -> FastEngine:
    return FastEngine(LIQ, {"a": 100.0, "b": 100.0, "c": 100.0})


def test_escrow_is_locked_then_refunded_beyond_the_fill() -> None:
    e = _engine()
    assert e.commit("a", 25.0)
    assert e.balances()["a"].cash == 75.0
    [r] = e.clear_batch([(SealedOrder(0, "a", Side.YES, 10.0, 0.9), 25.0)], [])
    assert r.ok and r.trade.shares == pytest.approx(10.0) and r.requested == 10.0
    assert e.balances()["a"].cash == pytest.approx(100.0 - r.cost)
    assert e.balances()["a"].position(Venue.MAIN, Side.YES) == pytest.approx(10.0)


def test_cannot_commit_without_the_escrow() -> None:
    assert not _engine().commit("a", 125.0)


def test_unrevealed_and_insolvent_commitments_are_slashed() -> None:
    e = _engine()
    e.commit("a", 5.0)
    e.commit("b", 5.0)
    insolvent = SealedOrder(1, "b", Side.YES, 100.0, 0.5)  # worst case 50 > escrow 5
    [receipt] = e.clear_batch([(insolvent, 5.0)], [("a", 5.0)])
    assert not receipt.ok and "slashed" in receipt.reason
    assert e.balances()[SLASHED_ID].cash == pytest.approx(10.0)
    assert e.balances()["a"].cash == 95.0 and e.balances()["b"].cash == 95.0


def test_matched_buyers_form_sets_and_money_is_conserved_through_resolution() -> None:
    e = _engine()
    start = _total(e)
    for agent in "abc":
        e.commit(agent, 25.0)
    orders = [(SealedOrder(0, "a", Side.YES, 20.0, 0.8), 25.0),
              (SealedOrder(1, "b", Side.NO, 15.0, 0.8), 25.0),
              (SealedOrder(2, "c", Side.YES, 5.0, 0.4), 25.0)]  # c's limit is below the clearing price
    receipts = e.clear_batch(orders, [])
    by_agent = {r.trade.agent_id: r for r in receipts}
    assert by_agent["c"].trade.shares == 0.0 and not by_agent["c"].ok
    p = by_agent["a"].cost / by_agent["a"].trade.shares
    assert by_agent["b"].cost / by_agent["b"].trade.shares == pytest.approx(1 - p)  # one uniform price
    assert e.state().venues[Venue.MAIN].q_yes == pytest.approx(5.0)  # only the imbalance hit the LMSR
    assert _total(e) == pytest.approx(start)
    e.resolve(1)
    assert _total(e) == pytest.approx(start)
    assert e.market_maker_pnl()[Venue.MAIN] >= -max_market_maker_loss(100.0) - 1e-9


def test_pairs_are_merged_after_clearing() -> None:
    e = _engine()
    e.commit("a", 25.0)
    e.clear_batch([(SealedOrder(0, "a", Side.YES, 10.0, 0.9), 25.0)], [])
    e.commit("a", 25.0)
    e.clear_batch([(SealedOrder(1, "a", Side.NO, 4.0, 0.9), 25.0)], [])  # reduce exposure by buying NO
    acct = e.balances()["a"]
    assert acct.position(Venue.MAIN, Side.YES) == pytest.approx(6.0)
    assert acct.position(Venue.MAIN, Side.NO) == pytest.approx(0.0)
    assert e.balances()[BUILDER_ID].cash == 0.0
