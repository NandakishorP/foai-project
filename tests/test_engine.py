import math

import pytest

from tfs.core.types import Bundle, Side, Trade, Venue
from tfs.engines.fast import FastEngine
from tfs.market.lmsr import max_market_maker_loss

LIQ = {Venue.MAIN: 100.0, Venue.REF: 30.0}


def _engine() -> FastEngine:
    return FastEngine(LIQ, {"a": 100.0, "b": 100.0})


def _total_cash(engine: FastEngine) -> float:
    return sum(acct.cash for acct in engine.balances().values()) + sum(
        v.collateral for v in engine.state().venues.values()
    )


def test_buy_moves_cash_and_shares() -> None:
    e = _engine()
    [r] = e.submit(Trade("a", Venue.MAIN, Side.YES, 10.0, limit_price=1.0))
    assert r.ok and r.cost > 0 and r.price_after > r.price_before
    acct = e.balances()["a"]
    assert acct.position(Venue.MAIN, Side.YES) == 10.0
    assert acct.cash == pytest.approx(100.0 - r.cost)


def test_collateral_is_conserved_through_trading_and_resolution() -> None:
    e = _engine()
    start = _total_cash(e)
    e.build_block(
        [
            Trade("a", Venue.MAIN, Side.YES, 30.0, 1.0),
            Trade("b", Venue.MAIN, Side.NO, 10.0, 1.0),
            Trade("b", Venue.REF, Side.YES, 5.0, 1.0),
            Trade("a", Venue.MAIN, Side.YES, -12.0, 0.0),
        ]
    )
    assert _total_cash(e) == pytest.approx(start)
    e.resolve(1)
    assert _total_cash(e) == pytest.approx(start)
    for venue, pnl in e.market_maker_pnl().items():
        assert pnl >= -max_market_maker_loss(LIQ[venue])


def test_resolution_pays_winning_side_only() -> None:
    e = _engine()
    e.submit(Trade("a", Venue.MAIN, Side.YES, 10.0, 1.0))
    e.submit(Trade("b", Venue.MAIN, Side.NO, 10.0, 1.0))
    cash_before = {k: v.cash for k, v in e.balances().items()}
    e.resolve(0)
    after = e.balances()
    assert after["a"].cash == pytest.approx(cash_before["a"])
    assert after["b"].cash == pytest.approx(cash_before["b"] + 10.0)
    assert not after["a"].shares and not after["b"].shares


def test_limit_violation_reverts() -> None:
    e = _engine()
    [r] = e.submit(Trade("a", Venue.MAIN, Side.YES, 50.0, limit_price=0.51))  # avg price ~0.56
    assert not r.ok and r.reason == "limit"
    assert e.prices()[Venue.MAIN] == pytest.approx(0.5)
    assert e.balances()["a"].cash == 100.0


def test_insufficient_cash_and_shares_revert() -> None:
    e = _engine()
    [r1] = e.submit(Trade("a", Venue.MAIN, Side.YES, 500.0, 1.0))
    assert not r1.ok and r1.reason == "insufficient cash"
    [r2] = e.submit(Trade("a", Venue.MAIN, Side.YES, -1.0, 0.0))
    assert not r2.ok and r2.reason == "insufficient shares"


def test_bundle_is_all_or_nothing() -> None:
    e = _engine()
    good = Trade("a", Venue.REF, Side.YES, 5.0, 1.0)
    bad = Trade("a", Venue.MAIN, Side.NO, 5.0, limit_price=0.01)  # cannot fill at 1 cent
    receipts = e.submit(Bundle("a", (good, bad)))
    assert [r.ok for r in receipts] == [False, False]
    assert e.prices()[Venue.REF] == pytest.approx(0.5)
    assert e.balances()["a"].cash == 100.0
    assert e.balances()["a"].position(Venue.REF, Side.YES) == 0.0


def test_unknown_agent_is_a_programming_error() -> None:
    from tfs.engines.fast import EngineError

    with pytest.raises(EngineError):
        _engine().submit(Trade("ghost", Venue.MAIN, Side.YES, 1.0, 1.0))


def test_same_transactions_same_state() -> None:
    txs = [Trade("a", Venue.MAIN, Side.YES, 7.0, 1.0), Trade("b", Venue.MAIN, Side.NO, 3.0, 1.0)]
    e1, e2 = _engine(), _engine()
    e1.build_block(txs)
    e2.build_block(txs)
    assert e1.state() == e2.state()
    assert math.isclose(e1.balances()["a"].cash, e2.balances()["a"].cash)
