"""EvmEngine basics on a private Anvil (skipped if the project-local Foundry or web3 is missing)."""

import pytest

from tfs.core.types import Bundle, Side, Trade, Venue
from tfs.engines.anvil import anvil_available

pytestmark = [
    pytest.mark.evm,
    pytest.mark.skipif(not anvil_available(), reason="project-local Foundry not installed (make foundry)"),
]
web3 = pytest.importorskip("web3")

from tfs.engines.evm import EvmEngine  # noqa: E402

LIQ = {Venue.MAIN: 100.0, Venue.REF: 30.0}


@pytest.fixture(scope="module")
def engine():
    with EvmEngine(LIQ, {"a": 100.0, "b": 100.0, "p": 200.0}, base_fee=0.01) as e:
        yield e


def test_starts_at_half_with_funded_accounts(engine: EvmEngine) -> None:
    assert engine.prices() == {Venue.MAIN: 0.5, Venue.REF: 0.5}
    assert engine.balances()["a"].cash == pytest.approx(100.0)


def test_block_order_is_the_builder_order(engine: EvmEngine) -> None:
    """FIFO: the second buy in the block pays more than the first, as in the order sent."""
    first, second = engine.build_block([Trade("a", Venue.MAIN, Side.YES, 5.0, 1.0),
                                        Trade("b", Venue.MAIN, Side.YES, 5.0, 1.0)])
    assert first.ok and second.ok
    assert second.price_before == pytest.approx(first.price_after)
    assert second.cost > first.cost


def test_fees_and_revert_protection(engine: EvmEngine) -> None:
    before = engine.builder_revenue()
    [plain] = engine.build_block([Trade("a", Venue.MAIN, Side.YES, 5.0, 0.01, priority_fee=0.1)])
    assert not plain.ok
    assert engine.builder_revenue() == pytest.approx(before + 0.11)  # failed plain trade still pays
    [protected] = engine.build_block([Trade("p", Venue.MAIN, Side.YES, 5.0, 0.01, priority_fee=0.1,
                                            revert_protected=True)])
    assert not protected.ok
    assert engine.builder_revenue() == pytest.approx(before + 0.11)  # protected failure pays nothing


def test_bundle_all_or_nothing(engine: EvmEngine) -> None:
    cash = engine.balances()["b"].cash
    receipts = engine.build_block([Bundle("b", (Trade("b", Venue.REF, Side.YES, 2.0, 1.0),
                                                Trade("b", Venue.MAIN, Side.NO, 2.0, 0.01)))])
    assert [r.ok for r in receipts] == [False, False]
    assert engine.balances()["b"].cash == pytest.approx(cash)
