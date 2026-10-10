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
