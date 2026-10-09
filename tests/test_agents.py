import math

import numpy as np
import pytest

from tfs.agents.arbitrageur import Arbitrageur
from tfs.agents.base import Observation
from tfs.agents.beliefs import OwnSignalsBelief, PriceAnchoredBelief
from tfs.agents.forecaster import InformedForecaster
from tfs.agents.kelly import kelly_fraction, kelly_target_net_yes
from tfs.agents.noise import NoiseTrader
from tfs.agents.trend import TrendFollower
from tfs.core.types import Account, Receipt, Side, Trade, Venue
from tfs.engines.fast import FastEngine
from tfs.market.lmsr import logit, sigmoid


def _obs(price: float = 0.5, public: float = 0.0, private: float = 0.0, account: Account | None = None,
         receipts: tuple[Receipt, ...] = (), ref_price: float = 0.5, tick: int = 0) -> Observation:
    return Observation(
        tick=tick,
        prices={Venue.MAIN: price, Venue.REF: ref_price},
        public_llr=public,
        private_llr=private,
        account=account or Account(cash=100.0),
        receipts=receipts,
    )


def _forecaster(belief=None, b: float = 100.0) -> InformedForecaster:
    return InformedForecaster(
        index=0, liquidity=b, belief=belief or OwnSignalsBelief(0.0), kelly_fraction=0.25,
        bankroll=100.0, max_order=50.0, min_order=0.5, public_latency=0,
    )


# ----------------------------------------------------------------- Kelly sizing


def test_kelly_zero_without_edge_and_symmetric() -> None:
    assert kelly_fraction(0.6, 0.6, 0.25) == 0.0
    assert kelly_fraction(0.7, 0.5, 0.25) == pytest.approx(-kelly_fraction(0.3, 0.5, 0.25))
    assert kelly_fraction(0.8, 0.6, 1.0) == pytest.approx((0.8 - 0.6) / (1 - 0.6))
    assert kelly_target_net_yes(0.7, 0.5, 0.25, 100.0) > 0 > kelly_target_net_yes(0.3, 0.5, 0.25, 100.0)


# --------------------------------------------------------------------- beliefs


def test_own_signals_belief_is_order_invariant() -> None:
    a, b = OwnSignalsBelief(0.2), OwnSignalsBelief(0.2)
    for llr in (0.5, -1.0, 0.3):
        a.observe(llr)
    for llr in (0.3, 0.5, -1.0):
        b.observe(llr)
    assert a.probability(0.1) == pytest.approx(b.probability(0.9))  # price is ignored
    assert a.probability(0.5) == pytest.approx(sigmoid(0.2 - 0.2))


def test_price_anchored_residual_shrinks_by_own_impact_without_flipping() -> None:
    belief = PriceAnchoredBelief()
    belief.observe(1.0)
    assert belief.probability(0.5) == pytest.approx(sigmoid(1.0))
    trade = Trade("x", Venue.MAIN, Side.YES, 1.0, 1.0)
    belief.on_own_fill(Receipt(trade, True, "", 0.5, price_before=0.5, price_after=sigmoid(0.4)))
    assert belief.residual == pytest.approx(0.6)
    belief.on_own_fill(Receipt(trade, True, "", 0.5, price_before=sigmoid(0.4), price_after=sigmoid(2.0)))
    assert belief.residual == 0.0  # overshoot does not create opposite information


# ----------------------------------------------------------------- forecaster


def test_forecaster_with_yes_signal_buys_yes_without_pushing_past_belief() -> None:
    f = _forecaster()
    f.perceive(_obs(private=2.0))
    [trade] = f.act()
    belief = sigmoid(2.0)
    assert trade.side is Side.YES and trade.shares > 0
    assert trade.limit_price == pytest.approx(belief)
    assert trade.shares <= 100.0 * (logit(belief) - logit(0.5)) + 1e-9


def test_forecaster_sells_opposite_side_first() -> None:
    f = _forecaster()
    f.perceive(_obs(private=2.0, account=Account(cash=100.0, shares={(Venue.MAIN, Side.NO): 5.0})))
    [trade] = f.act()
    assert trade.side is Side.NO and trade.shares == pytest.approx(-5.0)


def test_forecaster_stops_at_kelly_target() -> None:
    f = _forecaster()
    target = kelly_target_net_yes(sigmoid(1.0), 0.5, 0.25, 100.0)
    f.perceive(_obs(private=1.0, account=Account(cash=50.0, shares={(Venue.MAIN, Side.YES): target + 1})))
    assert f.act() == []


def test_price_anchored_forecaster_ignores_public_news() -> None:
    f = _forecaster(belief=PriceAnchoredBelief())
    f.perceive(_obs(public=3.0))
    assert f.act() == []


# ---------------------------------------------------------- other agent types


def test_noise_arrivals_match_poisson_rate() -> None:
    trader = NoiseTrader("n", Venue.MAIN, rate=0.3, mean_size=2.0, bankroll=1e6, rng=np.random.default_rng(1))
    orders = [o for _ in range(5000) for o in trader.act()]
    assert len(orders) / 5000 == pytest.approx(0.3, rel=0.08)
    assert np.mean([o.shares for o in orders]) == pytest.approx(2.0, rel=0.08)


def test_arbitrage_equalises_prices_and_locks_in_profit() -> None:
    liq = {Venue.MAIN: 100.0, Venue.REF: 30.0}
    engine = FastEngine(liq, {"setup": 1000.0, "arb": 500.0})
    engine.submit(Trade("setup", Venue.MAIN, Side.YES, 80.0, 1.0))  # main price ~0.69, ref 0.5
    arb = Arbitrageur("arb", liq, capital=500.0, min_profit=0.0, slippage=0.01)
    arb.perceive(_obs(price=engine.prices()[Venue.MAIN], ref_price=engine.prices()[Venue.REF],
                      account=engine.balances()["arb"]))
    [bundle] = arb.act()
    receipts = engine.submit(bundle)
    assert all(r.ok for r in receipts)
    prices = engine.prices()
    assert prices[Venue.MAIN] == pytest.approx(prices[Venue.REF], abs=1e-9)
    acct = engine.balances()["arb"]
    # holds x YES on one venue and x NO on the other: paid out x whatever happens
    held_yes = acct.position(Venue.REF, Side.YES)
    held_no = acct.position(Venue.MAIN, Side.NO)
    assert held_yes == pytest.approx(held_no)
    assert acct.cash + held_yes > 500.0


def test_trend_follower_buys_uptrend_and_sells_downtrend() -> None:
    t = TrendFollower("t", fast_span=3, slow_span=8, threshold=0.01, order_size=2.0, max_position=10.0, bankroll=100.0)
    for i in range(12):
        t.perceive(_obs(price=0.5 + 0.02 * i))
    [up] = t.act()
    assert up.side is Side.YES and up.shares > 0
    t2 = TrendFollower("t", fast_span=3, slow_span=8, threshold=0.01, order_size=2.0, max_position=10.0, bankroll=100.0)
    for i in range(12):
        t2.perceive(_obs(price=0.5 - 0.02 * i))
    [down] = t2.act()
    assert down.side is Side.NO and down.shares > 0


def test_trend_follower_waits_for_warmup() -> None:
    t = TrendFollower("t", fast_span=3, slow_span=8, threshold=0.0, order_size=2.0, max_position=10.0, bankroll=100.0)
    for i in range(5):
        t.perceive(_obs(price=0.5 + 0.05 * i))
    assert t.act() == []
    assert math.isfinite(t.fast or 0.0)
