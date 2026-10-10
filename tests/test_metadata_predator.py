"""Metadata copy-trading predator and the sealed-batch attackers (D-046, D-047)."""

import dataclasses

import pytest

from tfs.agents.base import Observation
from tfs.agents.metadata_predator import MetadataPredator
from tfs.agents.predator import PredatorMemory
from tfs.core.config import SimConfig, replace_in
from tfs.core.types import Account, Receipt, Side, Trade, Venue
from tfs.mempool.batch_desk import CommitMeta
from tfs.simulation import run_season

B = 100.0


def _predator(base_config: SimConfig, memory: PredatorMemory | None = None, proving_delay: int = 0) -> MetadataPredator:
    cfg = dataclasses.replace(base_config.agents.predators, count=1)
    return MetadataPredator("pred", B, cfg, memory or PredatorMemory(), market_ticks=200, batch_interval=5,
                            proving_delay=proving_delay)


def _obs(tick: int, commits=(), last_block=()) -> Observation:
    return Observation(tick, {Venue.MAIN: 0.5, Venue.REF: 0.5}, 0.0, 0.0, Account(cash=200.0), (), (),
                       tuple(last_block), tuple(commits))


def _revealed(agent: str, side: Side, filled: float) -> Receipt:
    return Receipt(Trade(agent, Venue.MAIN, side, filled, 0.9), filled > 0, "", 0.5 * filled, 0.5, 0.52, requested=10.0)


def test_predicted_move_uses_each_address_expected_continuation(base_config: SimConfig) -> None:
    memory = PredatorMemory(markout_ema={"inf": 0.3, "noise": 0.0})
    pred = _predator(base_config, memory)
    pred.perceive(_obs(1, last_block=[_revealed("inf", Side.YES, 10.0), _revealed("noise", Side.NO, 5.0)]))
    commits = [CommitMeta(0, 2, "inf", 25.0), CommitMeta(0, 3, "noise", 25.0)]
    move, aligned = pred._predicted_move(commits)
    assert move == pytest.approx((25 * 1 * 0.3 + 25 * -1 * 0.0) / 50)
    assert aligned == 25.0  # only the escrow pushing in the predicted direction


def test_a_relayer_leaves_nothing_to_copy(base_config: SimConfig) -> None:
    pred = _predator(base_config, PredatorMemory(markout_ema={"inf": 0.5}))
    pred.perceive(_obs(1, last_block=[_revealed("inf", Side.YES, 10.0)]))
    assert pred._predicted_move([CommitMeta(0, 2, None, 125.0)]) == (0.0, 0.0)


def test_orders_only_in_the_last_block_its_proof_allows(base_config: SimConfig) -> None:
    memory = PredatorMemory(markout_ema={"inf": 0.8})
    for delay, decision_tick in ((0, 4), (2, 2)):
        pred = _predator(base_config, memory, proving_delay=delay)
        pred.perceive(_obs(1, last_block=[_revealed("inf", Side.YES, 10.0)]))
        orders = {}
        for tick in range(1, 5):
            pred.perceive(_obs(tick, commits=[CommitMeta(0, 1, "inf", 125.0)]))
            orders[tick] = pred.batch_order()
        assert [t for t, o in orders.items() if o is not None] == [decision_tick]
        assert orders[decision_tick].side is Side.YES


def test_no_order_without_expected_continuation(base_config: SimConfig) -> None:
    pred = _predator(base_config, PredatorMemory(markout_ema={"inf": 0.0}))
    pred.perceive(_obs(1, last_block=[_revealed("inf", Side.YES, 10.0)]))
    pred.perceive(_obs(4, commits=[CommitMeta(0, 1, "inf", 125.0)]))
    assert pred.batch_order() is None


def test_own_fill_in_the_same_batch_is_not_subtracted_again(base_config: SimConfig) -> None:
    pred = _predator(base_config)
    own = Receipt(Trade("pred", Venue.MAIN, Side.YES, 20.0, 0.9), True, "", 10.0, 0.5, 0.55, requested=20.0)
    pred.perceive(_obs(5, last_block=[_revealed("inf", Side.YES, 10.0), own]))
    [watch] = pred._watches
    assert watch.own_impact == 0.0  # its own fill is already inside the post-clearing starting price


# ------------------------------------------------------------------ attackers


def _attacked(base_config: SimConfig, policy: str, **attackers: int):
    cfg = replace_in(replace_in(base_config, "season.n_markets", 1), "mempool.policy", policy)
    cfg = replace_in(cfg, "market.ticks", 120)  # 24 batches of 5 blocks
    for name, n in attackers.items():
        cfg = replace_in(cfg, f"agents.attackers.{name}", n)
    return run_season(cfg, 1).markets[0]


def test_griefer_never_reveals_and_is_slashed(base_config: SimConfig) -> None:
    m = _attacked(base_config, "zk_batch", non_reveal=1)
    assert m.unrevealed == 24 and m.slashed == pytest.approx(24 * 5.0)  # one commitment per 5-block batch
    assert m.pnl["griefer_0"] == pytest.approx(-120.0)


def test_spam_is_slashed_under_commit_reveal_and_impossible_under_zk(base_config: SimConfig) -> None:
    cr = _attacked(base_config, "commit_reveal", spam=1)
    zk = _attacked(base_config, "zk_batch", spam=1)
    assert cr.pnl["spam_0"] < 0 and cr.slashed > 0
    assert zk.pnl["spam_0"] == 0.0 and zk.slashed == 0.0


def test_free_option_reveals_at_most_one_side_per_batch(base_config: SimConfig) -> None:
    """Each slashed side forfeits its tier (25, or 5 once cash runs low and orders are cut to fit),
    so a 200-USDC identity soon stops committing."""
    m = _attacked(base_config, "zk_batch", free_option=1)
    commits_by_side = m.requested_by_kind
    assert m.unrevealed > 0
    assert 5.0 * m.unrevealed <= m.slashed <= 25.0 * m.unrevealed  # every withheld side forfeits its tier
    assert m.pnl["freeopt_0_yes"] + m.pnl["freeopt_0_no"] < 0  # slashing makes the option costly
    assert commits_by_side.get("attacker", 0.0) > 0
