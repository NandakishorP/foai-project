import pytest

from tfs.core.types import Bundle, Side, Trade, Venue
from tfs.engines.fast import BUILDER_ID, EngineError, FastEngine

LIQ = {Venue.MAIN: 100.0, Venue.REF: 30.0}


def _total(engine: FastEngine) -> float:
    return sum(a.cash for a in engine.balances().values()) + sum(v.collateral for v in engine.state().venues.values())


def test_fees_go_to_builder_and_conserve_cash() -> None:
    e = FastEngine(LIQ, {"a": 100.0}, base_fee=0.01)
    start = _total(e)
    [r] = e.submit(Trade("a", Venue.MAIN, Side.YES, 5.0, 1.0, priority_fee=0.2))
    assert r.ok
    assert e.builder_revenue() == pytest.approx(0.21)
    assert e.balances()["a"].cash == pytest.approx(100.0 - r.cost - 0.21)
    assert _total(e) == pytest.approx(start)


def test_reverted_trade_still_pays_its_fee() -> None:
    e = FastEngine(LIQ, {"a": 100.0}, base_fee=0.05)
    [r] = e.submit(Trade("a", Venue.MAIN, Side.YES, 50.0, limit_price=0.51, priority_fee=0.1))
    assert not r.ok and r.reason == "limit"
    assert e.builder_revenue() == pytest.approx(0.15)
    assert e.balances()["a"].cash == pytest.approx(99.85)


def test_reverted_bundle_pays_nothing() -> None:
    e = FastEngine(LIQ, {"a": 100.0}, base_fee=0.05)
    good = Trade("a", Venue.REF, Side.YES, 5.0, 1.0, priority_fee=0.1)
    bad = Trade("a", Venue.MAIN, Side.NO, 5.0, limit_price=0.01)
    e.submit(Bundle("a", (good, bad)))
    assert e.builder_revenue() == 0.0
    assert e.balances()["a"].cash == 100.0


def test_zero_fees_change_nothing() -> None:
    e = FastEngine(LIQ, {"a": 100.0})
    e.submit(Trade("a", Venue.MAIN, Side.YES, 5.0, 1.0))
    assert e.builder_revenue() == 0.0


def test_builder_id_is_reserved() -> None:
    with pytest.raises(EngineError):
        FastEngine(LIQ, {BUILDER_ID: 1.0})


def test_revert_protected_trade_pays_nothing_when_it_reverts() -> None:
    e = FastEngine(LIQ, {"p": 100.0}, base_fee=0.05)
    [r] = e.submit(Trade("p", Venue.MAIN, Side.YES, 50.0, limit_price=0.51, priority_fee=0.3, revert_protected=True))
    assert not r.ok
    assert e.builder_revenue() == 0.0 and e.balances()["p"].cash == 100.0
    [ok] = e.submit(Trade("p", Venue.MAIN, Side.YES, 5.0, 1.0, priority_fee=0.3, revert_protected=True))
    assert ok.ok and e.builder_revenue() == pytest.approx(0.35)
