"""BatchDesk routing rules (D-046): buys only, one order per batch, escrow tiers, proving delay, legging, metadata."""

import dataclasses

import pytest

from tfs.core.config import SimConfig
from tfs.core.types import Bundle, Side, Trade, Venue
from tfs.engines.fast import FastEngine
from tfs.mempool.batch_desk import BatchDesk, to_sealed

LIQ = {Venue.MAIN: 100.0, Venue.REF: 30.0}


def _desk(base_config: SimConfig, **changes) -> tuple[BatchDesk, FastEngine]:
    cfg = dataclasses.replace(base_config.mempool, policy="zk_batch", **changes)
    engine = FastEngine(LIQ, {"f": 1000.0, "n": 1000.0, "arb": 1000.0, "poor": 3.0})
    kinds = {"f": "forecaster", "n": "noise", "arb": "arbitrageur", "poor": "forecaster"}
    return BatchDesk(cfg, engine, kinds), engine


def test_sells_become_equivalent_buys() -> None:
    o = to_sealed(Trade("f", Venue.MAIN, Side.YES, -10.0, 0.3), 0)
    assert o.side is Side.NO and o.size == 10.0 and o.limit == pytest.approx(0.7)
    market = to_sealed(Trade("f", Venue.MAIN, Side.YES, 5.0, 1.0), 1)
    assert market.limit == pytest.approx(0.999)  # limits stay strictly inside (0, 1)


def test_one_order_per_identity_per_batch_but_noise_is_a_crowd(base_config: SimConfig) -> None:
    desk, _ = _desk(base_config)
    assert desk.seal(Trade("f", Venue.MAIN, Side.YES, 5.0, 0.8), tick=1)
    assert not desk.seal(Trade("f", Venue.MAIN, Side.YES, 5.0, 0.8), tick=2)  # same batch (K = 5)
    assert desk.seal(Trade("n", Venue.MAIN, Side.YES, 1.0, 1.0), tick=2)
    assert desk.seal(Trade("n", Venue.MAIN, Side.NO, 1.0, 1.0), tick=3)
    assert desk.seal(Trade("f", Venue.MAIN, Side.YES, 5.0, 0.8), tick=6)  # next batch


def test_escrow_tier_is_the_smallest_cover_and_orders_are_cut_to_fit(base_config: SimConfig) -> None:
    desk, engine = _desk(base_config)
    desk.seal(Trade("f", Venue.MAIN, Side.YES, 20.0, 0.8), tick=0)  # worst case 16 -> tier 25
    desk.seal(Trade("poor", Venue.MAIN, Side.YES, 20.0, 0.8), tick=0)  # only 3 USDC: cannot post any tier
    desk.commit_due(0)
    assert [(e.order.agent_id, e.escrow) for e in desk.book] == [("f", 25.0)]
    assert engine.balances()["f"].cash == 975.0


def test_proving_delay_can_push_an_order_into_the_next_batch(base_config: SimConfig) -> None:
    desk, _ = _desk(base_config, proving_delay=2)
    desk.seal(Trade("f", Venue.MAIN, Side.YES, 5.0, 0.8), tick=4)  # proof ready at tick 6: batch 1
    desk.commit_due(4)
    assert desk.book == []
    desk.commit_due(6)
    assert desk.batch_of(desk.book[0].commit_tick) == 1


def test_batch_clears_after_its_window_and_arbitrage_is_legged(base_config: SimConfig) -> None:
    desk, engine = _desk(base_config)
    bundle = Bundle("arb", (Trade("arb", Venue.REF, Side.YES, 6.0, 1.0), Trade("arb", Venue.MAIN, Side.NO, 6.0, 0.9)))
    continuous = desk.route([bundle, Trade("f", Venue.REF, Side.YES, 1.0, 1.0)], tick=2)
    assert len(continuous) == 1 and continuous[0].venue is Venue.REF  # only the plain ref trade stays continuous
    desk.commit_due(2)
    assert desk.clear_if_due(4) == []  # window still open
    [receipt] = desk.clear_if_due(5)
    assert receipt.ok and receipt.trade.side is Side.NO
    [leg] = desk.due_followups(6)
    assert leg.venue is Venue.REF and leg.shares == pytest.approx(6.0 * receipt.trade.shares / 6.0)
    assert desk.stats.delay_count == 1 and desk.stats.delay_sum == 3


def test_metadata_shows_sender_and_tier_but_not_contents(base_config: SimConfig) -> None:
    desk, _ = _desk(base_config)
    desk.seal(Trade("f", Venue.MAIN, Side.YES, 20.0, 0.8), tick=1)
    desk.commit_due(1)
    [meta] = desk.metadata
    assert (meta.sender, meta.tier, meta.batch, meta.tick) == ("f", 25.0, 0, 1)
    hidden, _ = _desk(base_config, sender_visible=False)
    hidden.seal(Trade("f", Venue.MAIN, Side.YES, 20.0, 0.8), tick=1)
    hidden.commit_due(1)
    assert hidden.metadata[0].sender is None


def test_no_predators_policies_differ_only_where_they_should(base_config: SimConfig) -> None:
    """Without predators, private relay is exactly public, and commit-reveal is exactly ZK (no attackers, no delay)."""
    from tfs.core.config import replace_in
    from tfs.simulation import run_season

    cfg = replace_in(replace_in(base_config, "season.n_markets", 2), "market.ticks", 120)
    runs = {p: run_season(replace_in(cfg, "mempool.policy", p), 3).markets[-1] for p in
            ("public", "private_relay", "commit_reveal", "zk_batch")}
    assert runs["public"].pnl == runs["private_relay"].pnl
    assert runs["commit_reveal"].pnl == runs["zk_batch"].pnl
    assert runs["public"].pnl != runs["zk_batch"].pnl
