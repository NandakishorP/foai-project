"""The truth-lost decomposition (DECISIONS D-001).

E[(p − p*_full)²] = E[(p − p*_avail)²] + E[(p*_avail − p*_full)²] holds because
the cross term E[(p − p*_avail)(p*_avail − p*_full)] is zero across seeds: the
market price uses only acquired information, and p*_avail is the best guess of
p*_full given that information. If this test fails, the information model, the
ideal prices, or the simulation leaks unacquired information into the market.
"""

import math

import numpy as np
import pytest

from tfs.core.config import SimConfig, load_config, replace_in
from tfs.core.information import draw_forecaster_traits
from tfs.core.rng import RngFactory
from tfs.metrics.accuracy import decompose
from tfs.simulation import run_market

from .conftest import CONFIG_DIR

N_SEEDS = 300
RESEARCHERS = frozenset({0, 2, 4, 6, 8})  # partial participation, so the participation gap is non-trivial


def _cross_terms(cfg: SimConfig, leak: float = 0.0) -> np.ndarray:
    """Per-seed cross term of the simulated market with partial participation.

    `leak` > 0 adds that fraction of the unacquired information (p*_full − p*_avail)
    to the market price: a deliberately broken market for the negative control.
    """
    out = []
    for seed in range(N_SEEDS):
        rngs = RngFactory(10_000 + seed)
        traits = draw_forecaster_traits(cfg, rngs)
        r = run_market(cfg, rngs, 0, traits, RESEARCHERS)
        price = r.price_main + leak * (r.p_full - r.p_avail)
        out.append(decompose(price, r.p_full, r.p_avail).cross_term)
    return np.array(out)


@pytest.fixture(scope="module")
def cfg() -> SimConfig:
    return replace_in(load_config(CONFIG_DIR / "base.yaml"), "market.ticks", 150)


@pytest.mark.parametrize(("model", "rho"), [("own_signals", 0.0), ("price_anchored", 0.0), ("own_signals", 0.6)])
def test_cross_term_averages_to_zero(cfg: SimConfig, model: str, rho: float) -> None:
    """Holds with correlated research only if p*_avail is the exact correlated posterior (D-024)."""
    cfg = replace_in(replace_in(cfg, "agents.belief_model", model), "information.private.rho", rho)
    cross = _cross_terms(cfg)
    se = cross.std(ddof=1) / math.sqrt(len(cross))
    assert abs(cross.mean()) < 3 * se, (cross.mean(), se)


def test_negative_control_detects_leaked_information(cfg: SimConfig) -> None:
    """A price that absorbs 50% of the unacquired information must give a clearly non-zero cross term.

    This shows the zero-cross-term test above has the power to detect a leak.
    (A more "natural" leak, letting non-researchers trade secretly, was tried
    first. It moved the cross term by only ~2 SE at 300 seeds, because under
    own_signals the market absorbs little of any single forecaster's private
    information. That is the under-aggregation issue E1 measures, DECISIONS D-013.)
    """
    # rho = 0: at rho = 1 any one researcher knows everything, so there would be nothing to leak
    cross = _cross_terms(replace_in(cfg, "information.private.rho", 0.0), leak=0.5)
    se = cross.std(ddof=1) / math.sqrt(len(cross))
    assert cross.mean() < -3 * se, (cross.mean(), se)


def test_per_run_identity(cfg: SimConfig) -> None:
    rngs = RngFactory(1)
    traits = draw_forecaster_traits(cfg, rngs)
    r = run_market(cfg, rngs, 0, traits, RESEARCHERS)
    d = decompose(r.price_main, r.p_full, r.p_avail)
    assert d.truth_mse == pytest.approx(d.aggregation_mse + d.participation_mse + 2 * d.cross_term)
