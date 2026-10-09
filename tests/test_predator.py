"""Predator tests, including the owner's amendments (D-033): markouts from the post-trade price, EV net of the exit."""

import dataclasses
import math

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tfs.agents.base import Observation
from tfs.agents.predator import AddressBelief, Predator, PredatorMemory, exposure_direction
from tfs.core.config import PredatorConfig, SimConfig, load_config
from tfs.core.types import Receipt, Side, Trade, Venue
from tfs.engines.fast import FastEngine
from tfs.market.lmsr import cost_at_price, logit
from tfs.mempool.mempool import PendingTx

from .conftest import CONFIG_DIR

B = 100.0
TICKS = 200


@pytest.fixture
def pcfg(base_config: SimConfig) -> PredatorConfig:
    return dataclasses.replace(base_config.agents.predators, count=1)


def _predator(cfg: PredatorConfig, memory: PredatorMemory | None = None) -> Predator:
    return Predator("pred", B, cfg, memory or PredatorMemory(), market_ticks=TICKS)


def _obs(tick: int, engine: FastEngine, own: tuple[Receipt, ...] = (), last_block: tuple[Receipt, ...] = (),
         visible: tuple[PendingTx, ...] = ()) -> Observation:
    return Observation(tick, engine.prices(), 0.0, 0.0, engine.balances()["pred"], own, visible, last_block)


def _engine(predator: Predator, **others: float) -> FastEngine:
    return FastEngine({Venue.MAIN: B, Venue.REF: 30.0}, {"pred": predator.bankroll, **others})


# ------------------------------------------------------------------ basics


def test_beta_posterior_and_p_informed() -> None:
    b = AddressBelief()
    assert b.continuation_rate == 0.5 and b.p_informed == 0.0
    for _ in range(8):
        b.update(True)
    assert b.continuation_rate == pytest.approx(0.9)
    assert b.p_informed == pytest.approx(0.8)


def test_exposure_direction() -> None:
    assert exposure_direction(Trade("a", Venue.MAIN, Side.YES, 1.0, 1.0)) == 1
    assert exposure_direction(Trade("a", Venue.MAIN, Side.NO, -1.0, 0.0)) == 1
    assert exposure_direction(Trade("a", Venue.MAIN, Side.NO, 1.0, 1.0)) == -1
    assert exposure_direction(Trade("a", Venue.MAIN, Side.YES, -1.0, 0.0)) == -1


# ------------------------------------------- amendment 1: posterior from markouts


def test_posterior_separates_informed_from_noise(pcfg: PredatorConfig) -> None:
    """Scripted market: 'inf' trades with 50-tick trends it creates; 'noise' trades random sides.

    The predator only watches (min_profit is huge). Markouts start after each trade's own execution,
    so the noise trader's posterior stays at the prior mean while the informed trader's rises.
    """
    pred = _predator(dataclasses.replace(pcfg, min_profit=1e9))
    engine = _engine(pred, inf=1e6, noise=1e6)
    rng = np.random.default_rng(0)
    last: tuple[Receipt, ...] = ()
    for tick in range(600):
        pred.perceive(_obs(tick, engine, last_block=last))
        assert pred.front_run_request() is None
        trend = 1 if (tick // 50) % 2 == 0 else -1
        noise_side = Side.YES if rng.random() < 0.5 else Side.NO
        block = [Trade("inf", Venue.MAIN, Side.YES if trend > 0 else Side.NO, 5.0, 1.0),
                 Trade("noise", Venue.MAIN, noise_side, 2.0, 1.0)]
        last = tuple(engine.build_block(block))
    noise, inf = pred.memory.beliefs["noise"], pred.memory.beliefs["inf"]
    assert abs(noise.continuation_rate - 0.5) < 0.08, noise
    assert inf.continuation_rate > 0.7, inf
    assert noise.p_informed < 0.16 < 0.4 < inf.p_informed
    assert pred.memory.drift_ema is not None and pred.memory.drift_ema > 0


def test_own_trades_inside_a_window_are_subtracted(pcfg: PredatorConfig) -> None:
    """If only the predator moves the price after a trade, that trade's markout is zero (a failure)."""
    pred = _predator(dataclasses.replace(pcfg, min_profit=1e9, horizon=3))
    engine = _engine(pred, a=1e6)
    last = tuple(engine.build_block([Trade("a", Venue.MAIN, Side.YES, 5.0, 1.0)]))
    pred.perceive(_obs(1, engine, last_block=last))
    own = tuple(engine.build_block([Trade("pred", Venue.MAIN, Side.YES, 30.0, 1.0)]))  # pushes the price a's way
    for tick in range(2, 6):
        pred.perceive(_obs(tick, engine, own=own, last_block=own))
        own = tuple(engine.build_block([]))
    assert pred.memory.beliefs["a"].beta == 2.0 and pred.memory.beliefs["a"].alpha == 1.0


# ------------------------------------------------ amendment 2: EV equals realised PnL


def _front_run_once(pred: Predator, engine: FastEngine, victim: Trade):
    pending = PendingTx(0, victim, arrival=0.1)
    pred.perceive(_obs(0, engine, visible=(pending,)))
    request = pred.front_run_request()
    assert request is not None and pred.last_decision is not None
    block = [request.front, victim] + ([request.back] if request.back else [])
    receipts = tuple(engine.build_block(block))
    assert all(r.ok for r in receipts)
    return request, pred.last_decision, receipts


def test_ev_equals_realised_pnl_for_the_sandwich(pcfg: PredatorConfig) -> None:
    pred = _predator(dataclasses.replace(pcfg, back_run=True))
    engine = _engine(pred, victim=1e4)
    _, decision, _ = _front_run_once(pred, engine, Trade("victim", Venue.MAIN, Side.YES, 20.0, 0.65))
    realised = engine.balances()["pred"].cash - pred.bankroll
    assert realised == pytest.approx(decision.ev_net, abs=1e-9)


def _hold_and_unwind(pred: Predator, engine: FastEngine, receipts, correct_by: float = 0.0) -> None:
    """Run ticks 1..H+1 with no news; optionally someone undoes `correct_by` shares of YES at tick 1."""
    own = tuple(r for r in receipts if r.trade.agent_id == "pred")
    last = receipts
    for tick in range(1, pred.cfg.horizon + 3):
        pred.perceive(_obs(tick, engine, own=own, last_block=last))
        block = pred.act()
        if tick == 1 and correct_by:
            block = [Trade("corrector", Venue.MAIN, Side.NO, correct_by, 1.0)] + block
        last = tuple(engine.build_block(block))
        own = tuple(r for r in last if r.trade.agent_id == "pred")


def test_ev_equals_realised_pnl_when_holding_in_a_frozen_market(pcfg: PredatorConfig) -> None:
    """Nobody trades after the victim, so the predator's own impact persists: EV with reversion 0 is exact."""
    pred = _predator(dataclasses.replace(pcfg, own_impact_reversion=0.0))
    engine = _engine(pred, victim=1e4)
    _, decision, receipts = _front_run_once(pred, engine, Trade("victim", Venue.MAIN, Side.YES, 20.0, 0.65))
    _hold_and_unwind(pred, engine, receipts)
    acct = engine.balances()["pred"]
    assert acct.position(Venue.MAIN, Side.YES) == pytest.approx(0.0, abs=1e-9)  # unwound at H + 1
    assert acct.cash - pred.bankroll == pytest.approx(decision.ev_net, abs=1e-9)


def test_ev_equals_realised_pnl_when_the_market_undoes_own_impact(pcfg: PredatorConfig) -> None:
    """Reference assumption (reversion 1): someone trades the predator's impact back; EV is then exact."""
    pred = _predator(pcfg)
    engine = _engine(pred, victim=1e4, corrector=1e4)
    request, decision, receipts = _front_run_once(pred, engine, Trade("victim", Venue.MAIN, Side.YES, 20.0, 0.65))
    _hold_and_unwind(pred, engine, receipts, correct_by=request.front.shares)
    assert engine.balances()["pred"].cash - pred.bankroll == pytest.approx(decision.ev_net, abs=1e-9)


# ------------------------------------------------------------ sizing and gating


@settings(max_examples=60, deadline=None)
@given(
    start=st.floats(min_value=-2.0, max_value=2.0),
    size=st.floats(min_value=1.0, max_value=40.0),
    slack=st.floats(min_value=0.002, max_value=0.2),
    yes=st.booleans(),
    back_run=st.booleans(),
)
def test_front_run_never_makes_the_victim_revert(start: float, size: float, slack: float, yes: bool, back_run: bool) -> None:
    cfg = dataclasses.replace(load_config(CONFIG_DIR / "base.yaml").agents.predators, back_run=back_run)
    pred = _predator(cfg)
    engine = _engine(pred, victim=1e4, setup=1e4)
    if start:
        engine.submit(Trade("setup", Venue.MAIN, Side.YES if start > 0 else Side.NO, abs(start) * B, 1.0))
    side = Side.YES if yes else Side.NO
    price = engine.prices()[Venue.MAIN]
    side_price = price if yes else 1 - price
    fair_avg = cost_at_price(price, B, side, size) / size
    victim = Trade("victim", Venue.MAIN, side, size, min(fair_avg + slack, 0.999))
    pending = PendingTx(0, victim, 0.1)
    pred.perceive(_obs(0, engine, visible=(pending,)))
    request = pred.front_run_request()
    if request is None:
        return
    receipts = engine.build_block([request.front, victim])
    assert receipts[1].ok, (side_price, receipts)


def test_skips_when_costs_exceed_the_expected_profit(pcfg: PredatorConfig) -> None:
    pred = Predator("pred", B, pcfg, PredatorMemory(), market_ticks=TICKS, base_fee=5.0)
    engine = _engine(pred, victim=1e4)
    pred.perceive(_obs(0, engine, visible=(PendingTx(0, Trade("victim", Venue.MAIN, Side.YES, 20.0, 0.65), 0.1),)))
    assert pred.front_run_request() is None


def test_no_new_positions_it_could_not_unwind(pcfg: PredatorConfig) -> None:
    pred = _predator(dataclasses.replace(pcfg, back_run=True))
    engine = _engine(pred, victim=1e4)
    victim = PendingTx(0, Trade("victim", Venue.MAIN, Side.YES, 20.0, 0.65), 0.1)
    pred.perceive(Observation(TICKS - pcfg.horizon - 1, engine.prices(), 0.0, 0.0, engine.balances()["pred"], (), (victim,)))
    assert pred.front_run_request() is None


def test_slot_price_replays_visible_trades_ahead_of_the_victim(pcfg: PredatorConfig) -> None:
    pred = _predator(pcfg)
    engine = _engine(pred)
    ahead = PendingTx(0, Trade("a", Venue.MAIN, Side.YES, 30.0, 1.0), arrival=0.1)
    too_tight = PendingTx(1, Trade("b", Venue.MAIN, Side.YES, 10.0, 0.4), arrival=0.2)  # would revert: skipped
    victim = PendingTx(2, Trade("v", Venue.MAIN, Side.YES, 5.0, 1.0), arrival=0.3)
    after = PendingTx(3, Trade("c", Venue.MAIN, Side.NO, 50.0, 1.0), arrival=0.4)
    pred.perceive(_obs(0, engine, visible=(victim, after, too_tight, ahead)))
    assert pred.slot_logodds(victim) == pytest.approx(logit(0.5) + 30.0 / B)
    assert math.isclose(pred.slot_logodds(ahead), 0.0, abs_tol=1e-12)
