import hashlib

import numpy as np

from tfs.core.config import SimConfig, load_config, replace_in
from tfs.core.types import Bundle, Side, Trade, Venue
from tfs.mempool.builder import FeeBuilder, FrontRunRequest
from tfs.mempool.mempool import Mempool, MempoolPolicy
from tfs.simulation import run_season

from .conftest import CONFIG_DIR


def _trade(agent: str, fee: float = 0.0, shares: float = 1.0) -> Trade:
    return Trade(agent, Venue.MAIN, Side.YES, shares, 1.0, priority_fee=fee)


# --------------------------------------------------------------------- mempool


def test_arrivals_are_a_seeded_even_spread() -> None:
    pool = Mempool(MempoolPolicy.PUBLIC, np.random.default_rng(3))
    pending = pool.admit([_trade(f"a{i}") for i in range(4)])
    assert sorted(p.arrival for p in pending) == [0.125, 0.375, 0.625, 0.875]
    assert [p.tx_id for p in pending] == [0, 1, 2, 3]
    assert [p.tx_id for p in pool.admit([_trade("b")])] == [4]  # ids keep counting within a market


def test_visibility_depends_on_latency() -> None:
    pool = Mempool(MempoolPolicy.PUBLIC, np.random.default_rng(0))
    pending = pool.admit([_trade(f"a{i}") for i in range(4)])
    assert len(pool.visible_to(pending, 0.0)) == 4
    assert {p.arrival for p in pool.visible_to(pending, 0.3)} == {0.125, 0.375, 0.625}  # 0.875 + 0.3 >= 1
    assert pool.visible_to(pending, 0.99) == []


def test_admit_with_no_transactions_still_draws() -> None:
    """The stream advances every tick, so later blocks do not depend on whether earlier ones were empty."""
    a = Mempool(MempoolPolicy.PUBLIC, np.random.default_rng(1))
    b = Mempool(MempoolPolicy.PUBLIC, np.random.default_rng(1))
    a.admit([])
    b.admit([])
    assert [p.arrival for p in a.admit([_trade("x"), _trade("y")])] == [p.arrival for p in b.admit([_trade("x"), _trade("y")])]


# --------------------------------------------------------------------- builder


def test_builder_orders_by_fee_then_arrival() -> None:
    pool = Mempool(MempoolPolicy.PUBLIC, np.random.default_rng(0))
    pending = pool.admit([_trade("cheap"), _trade("rich", fee=0.5), _trade("cheap2")])
    plan = FeeBuilder().order(pending)
    assert plan.txs[0].agent_id == "rich"
    rest = [p for p in sorted(pending, key=lambda p: p.arrival) if p.sender != "rich"]
    assert [t.agent_id for t in plan.txs[1:]] == [p.sender for p in rest]


def test_front_run_is_placed_around_its_victim_and_highest_bid_wins() -> None:
    pool = Mempool(MempoolPolicy.PUBLIC, np.random.default_rng(0))
    pending = pool.admit([_trade("victim"), _trade("other")])
    victim = next(p for p in pending if p.sender == "victim")
    low = FrontRunRequest("pred_a", victim.tx_id, _trade("pred_a", fee=0.1))
    high = FrontRunRequest("pred_b", victim.tx_id, _trade("pred_b", fee=0.3), back=_trade("pred_b", shares=-1.0))
    plan = FeeBuilder().order(pending, [low, high], late_txs=[_trade("late")])
    senders = [t.agent_id for t in plan.txs]
    i = senders.index("victim")
    assert senders[i - 1 : i + 2] == ["pred_b", "victim", "pred_b"]
    assert "pred_a" not in senders
    assert senders[-1] == "late"
    assert [req.agent_id for req, _ in plan.placements] == ["pred_b"]


def test_equal_bids_tie_break_by_agent_id() -> None:
    pool = Mempool(MempoolPolicy.PUBLIC, np.random.default_rng(0))
    [victim] = pool.admit([_trade("victim")])
    reqs = [FrontRunRequest(a, victim.tx_id, _trade(a, fee=0.2)) for a in ("pred_z", "pred_a")]
    assert FeeBuilder().order([victim], reqs).placements[0][0].agent_id == "pred_a"


def test_bundle_fee_is_its_largest_trade_fee() -> None:
    from tfs.mempool.mempool import priority_fee

    assert priority_fee(Bundle("a", (_trade("a", fee=0.1), _trade("a", fee=0.4)))) == 0.4


# ----------------------------------------------------------------- regression


def test_no_predators_reproduces_phase_1_exactly() -> None:
    """Digest of prices, PnL and researchers taken at commit b803d95, before any Phase 2a code (D-033)."""
    cfg: SimConfig = replace_in(load_config(CONFIG_DIR / "season_baseline.yaml"), "season.n_markets", 4)
    h = hashlib.sha256()
    for seed in range(3):
        for m in run_season(cfg, seed).markets:
            h.update(m.price_main.tobytes())
            h.update(m.price_ref.tobytes())
            h.update(repr(sorted(m.pnl.items())).encode())
            h.update(repr(sorted(m.researchers)).encode())
    assert h.hexdigest() == "d99b9b2c67ac3b8396a751a6dce24a4aae92e3987dddccfe17b777f8752edc97"
