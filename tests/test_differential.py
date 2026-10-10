"""FastEngine vs EvmEngine on identical ordered blocks (SPEC §3.3; tolerance DECISIONS D-043)."""

import pytest

from tfs.core.types import Venue
from tfs.engines.anvil import anvil_available

pytestmark = [
    pytest.mark.evm,
    pytest.mark.skipif(not anvil_available(), reason="project-local Foundry not installed (make foundry)"),
]
pytest.importorskip("web3")

from tfs.core.config import load_config, replace_in  # noqa: E402
from tfs.engines.differential import compare, fuzz_blocks, traced_market  # noqa: E402

from .conftest import CONFIG_DIR  # noqa: E402


def _check(report) -> None:
    assert report.passed, report.summary() + "\n" + "\n".join(report.flag_mismatches[:10])


def test_fuzz_scenario() -> None:
    cash, blocks = fuzz_blocks(60, seed=1)
    _check(compare("fuzz", {Venue.MAIN: 100.0, Venue.REF: 30.0}, cash, blocks, 1, 0.01))


@pytest.mark.slow
@pytest.mark.parametrize(("cfg_name", "seed", "market", "predators"),
                         [("e2a", 3, 15, 1), ("season_baseline", 1, 0, 0)])
def test_simulated_market(cfg_name: str, seed: int, market: int, predators: int) -> None:
    cfg = replace_in(load_config(CONFIG_DIR / f"{cfg_name}.yaml"), "agents.predators.count", predators)
    cash, blocks, y = traced_market(cfg, seed, market)
    _check(compare(cfg_name, {Venue.MAIN: cfg.market.b_main, Venue.REF: cfg.market.b_ref},
                   cash, blocks, y, cfg.mempool.base_fee))


# ---- sealed batches (Phase 3a): FastEngine.clear_batch vs SealedBatchAuction ----

def test_batch_fuzz_scenario() -> None:
    from tfs.engines.differential import compare_batches, fuzz_batches

    cash, batches = fuzz_batches(20, seed=1)
    _check(compare_batches("batch fuzz", 100.0, cash, batches, 1, 5, [5.0, 25.0, 125.0, 625.0]))


@pytest.mark.slow
def test_batch_simulated_zk_market() -> None:
    from tfs.engines.differential import compare_batches, traced_batches

    cfg = load_config(CONFIG_DIR / "base.yaml")
    for key, value in [("mempool.policy", "zk_batch"), ("agents.predators.count", 1),
                       ("agents.attackers.non_reveal", 1), ("agents.attackers.free_option", 1)]:
        cfg = replace_in(cfg, key, value)
    cash, log, y = traced_batches(cfg, 3, 15)
    _check(compare_batches("zk market", cfg.market.b_main, cash, log, y, cfg.mempool.batch_interval,
                           list(cfg.mempool.escrow_tiers)))
