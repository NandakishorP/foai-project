"""Shock scenarios (D-053): false news and its correction, the depeg, and the stability metrics."""

import dataclasses
import math

import numpy as np
import pytest

from tfs.agents.arbitrageur import Arbitrageur
from tfs.agents.base import Observation
from tfs.agents.noise import NoiseTrader
from tfs.core.config import ShockConfig, SimConfig, load_config, replace_in
from tfs.core.information import draw_forecaster_traits, generate_tape, mixture_llr
from tfs.core.rng import RngFactory
from tfs.core.types import Account, Side, Venue
from tfs.market.lmsr import cost_at_price
from tfs.metrics.accuracy import decompose
from tfs.metrics.stability import WINDOW, event_metrics, events
from tfs.simulation import run_market, run_season

from .conftest import CONFIG_DIR

BASE = load_config(CONFIG_DIR / "base.yaml")


def shocked(status: str, q_false: float, nats: float = 3.0) -> SimConfig:
    cfg = replace_in(BASE, "information.q_false", q_false)
    return replace_in(cfg, "information.shocks", (ShockConfig(tick=100, nats=nats, status=status),))


# --------------------------------------------------------------------------- false news


def test_mixture_llr_discounts_but_never_reverses() -> None:
    assert mixture_llr(1.7, 0.0) == 1.7  # exactly: earlier results are unchanged
    for llr in (0.3, 2.0, 6.0):
        for q in (0.1, 0.2, 0.4):
            mixed = mixture_llr(llr, q)
            assert 0.0 < mixed < llr
            assert mixture_llr(-llr, q) == pytest.approx(-mixed)  # symmetric


def test_a_false_shock_points_the_wrong_way_and_the_correction_makes_it_exact() -> None:
    cfg = shocked("false", 0.2)
    wrong = []
    for seed in range(200):
        tape = generate_tape(cfg, RngFactory(seed), 0)
        sign = 1 if tape.y == 1 else -1
        assert tape.shock_false == (True,) and tape.correction_ticks == (120,)
        wrong.append(sign * tape.public_llr[100] < 0)
    assert np.mean(wrong) > 0.8


def test_known_false_news_ends_up_informative() -> None:
    """After the correction, a false shock's signal counts with the reversed sign: it points to the truth."""
    cfg = shocked("false", 0.2)
    total = []
    for seed in range(200):
        tape = generate_tape(cfg, RngFactory(seed), 0)
        sign = 1 if tape.y == 1 else -1
        total.append(sign * (tape.public_llr[100] + tape.public_llr[120]))
    assert np.mean(total) > 1.0  # the 3-nat signal, now read correctly


def test_cross_term_still_vanishes_when_shocks_are_drawn_false() -> None:
    """The ideal prices use the true likelihood of false news, so the decomposition (D-001) still holds."""
    cfg = replace_in(replace_in(shocked("drawn", 0.3), "information.private.rho", 0.0), "market.ticks", 150)
    cross = []
    for seed in range(300):
        rngs = RngFactory(20_000 + seed)
        r = run_market(cfg, rngs, 0, draw_forecaster_traits(cfg, rngs), frozenset({0, 2, 4, 6, 8}))
        cross.append(decompose(r.price_main, r.p_full, r.p_avail).cross_term)
    cross = np.array(cross)
    assert abs(cross.mean()) < 3 * cross.std(ddof=1) / math.sqrt(len(cross))


# --------------------------------------------------------------------------- depeg


def _obs(main: float, ref: float, collateral: float) -> Observation:
    return Observation(tick=0, prices={Venue.MAIN: main, Venue.REF: ref}, public_llr=0.0, private_llr=0.0,
                       account=Account(cash=500.0), receipts=(), main_collateral=collateral)


def _arb() -> Arbitrageur:
    return Arbitrageur("arb_0", {Venue.MAIN: 100.0, Venue.REF: 30.0}, 500.0, 0.05, 0.02)


def test_depeg_widens_the_arbitrage_band() -> None:
    arb = _arb()
    arb.perceive(_obs(0.60, 0.50, 1.0))
    pegged = arb.best_bundle()
    arb.perceive(_obs(0.60, 0.50, 0.90))
    depegged = arb.best_bundle()
    assert pegged is not None
    assert depegged is None or depegged.trades[0].shares < pegged.trades[0].shares


def test_depeg_bundle_locks_in_a_dollar_profit_whatever_the_outcome() -> None:
    arb = _arb()
    arb.perceive(_obs(0.80, 0.40, 0.90))  # a gap large enough to survive the depeg
    bundle = arb.best_bundle()
    assert bundle is not None
    by_venue = {t.venue: t for t in bundle.trades}
    x = by_venue[Venue.MAIN].shares
    cost_ref_yes = cost_at_price(0.40, 30.0, Side.YES, x)  # cheap venue: reference, collateral worth 1
    cost_main_no = cost_at_price(0.80, 100.0, Side.NO, x)  # dear venue: main, collateral worth 0.9
    worst = min(x * 1.0, x * 0.9) - cost_ref_yes * 1.0 - cost_main_no * 0.9
    assert worst >= 0.05 - 1e-9


def test_withdrawn_noise_trader_keeps_its_random_stream() -> None:
    def orders(away: range) -> list:
        trader = NoiseTrader("noise_main_0", Venue.MAIN, 0.5, 3.0, 1000.0, np.random.default_rng(7))
        trader.away = away
        out = []
        for tick in range(60):
            trader.perceive(dataclasses.replace(_obs(0.5, 0.5, 1.0), tick=tick))
            out.append([(o.side, o.shares) for o in trader.act()])
        return out

    present, absent = orders(range(0)), orders(range(20, 40))
    assert all(not o for o in absent[20:40])
    assert absent[:20] == present[:20] and absent[40:] == present[40:]


# --------------------------------------------------------------------------- stability metrics


def _shock_record():
    cfg = replace_in(shocked("true", 0.2, nats=1.0), "agents.forecasters.research.mode", "always")
    return run_season(cfg, seed=4).markets[0]


def test_stability_metrics_are_well_formed() -> None:
    record = _shock_record()
    evs = events(record, None)
    assert evs == {"shock": 100, "correction": 120}
    m = event_metrics(record, "shock", evs, 0.05)
    assert 0 <= m.recovery <= 20  # the window ends at the correction
    assert m.max_deviation >= 0 and m.overshoot >= 0 and 0 <= m.revert_share <= 1
    assert 0 <= m.gap_halflife <= 20


def test_a_price_glued_to_p_avail_is_perfectly_stable() -> None:
    record = _shock_record()
    glued = dataclasses.replace(record, price_main=record.p_avail.copy())
    m = event_metrics(glued, "correction", events(glued, None), 0.05)
    assert m.recovery == 0 and m.max_deviation == 0 and m.overshoot == 0
    assert WINDOW == 40
