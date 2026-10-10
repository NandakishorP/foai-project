"""H3 rules (every branch) and the joint statistics on synthetic per-seed data."""

import numpy as np
import pytest

from tfs.experiments import h3
from tfs.experiments.verdicts import CONTRADICTED, PARTLY, SUPPORTED
from tfs.metrics.paired import Interval


def iv(lo: float, hi: float) -> Interval:
    return Interval((lo + hi) / 2, lo, hi)


def test_h3a_rules() -> None:
    assert h3.h3a_verdict(iv(0.1, 0.5)) == SUPPORTED
    assert h3.h3a_verdict(iv(0.3, 0.6)) == PARTLY
    assert h3.h3a_verdict(iv(0.9, 1.4)) == CONTRADICTED


def test_h3b_rules() -> None:
    assert h3.h3b_verdict(iv(1.12, 1.3), iv(11, 20)) == SUPPORTED
    assert h3.h3b_verdict(iv(1.12, 1.3), iv(5, 20)) == PARTLY
    assert h3.h3b_verdict(iv(0.8, 1.0), iv(30, 40)) == CONTRADICTED


def test_h3c_rules() -> None:
    assert h3.h3c_verdict(iv(1, 10), iv(2, 5)) == SUPPORTED
    assert h3.h3c_verdict(iv(1, 12), iv(2, 5)) == PARTLY  # upper CI above 2K
    assert h3.h3c_verdict(iv(-3, 0), iv(2, 5)) == CONTRADICTED  # no measurable cost
    assert h3.h3c_verdict(iv(16, 20), iv(2, 5)) == CONTRADICTED  # cost compounds beyond 3K


def test_h3_overall_rules() -> None:
    assert h3.h3_overall_verdict(SUPPORTED, PARTLY, iv(-0.2, -0.01), iv(1, 5)) == SUPPORTED
    assert h3.h3_overall_verdict(SUPPORTED, CONTRADICTED, iv(-0.2, -0.01), iv(1, 5)) == PARTLY
    assert h3.h3_overall_verdict(CONTRADICTED, SUPPORTED, iv(-0.2, -0.01), iv(1, 5)) == CONTRADICTED
    assert h3.h3_overall_verdict(SUPPORTED, SUPPORTED, iv(0.0, 0.1), iv(1, 5)) == CONTRADICTED


def _cells(values: dict[str, float], n: int = 200, column: str = "x") -> dict[str, dict[str, np.ndarray]]:
    rng = np.random.default_rng(0)
    return {c: {column: v + rng.normal(0, 0.01, n)} for c, v in values.items()}


def test_interaction_decomposes_exactly() -> None:
    cells = _cells({h3.PUB0: 1.0, h3.PUB1: 1.5, h3.ZK0: 0.7, h3.ZK1: 0.8})
    out = h3.interaction(cells, "x")
    assert out["total"].point == pytest.approx(out["anti_crowding"].point + out["anti_predator"].point)
    assert out["anti_crowding"].point == pytest.approx(0.3, abs=0.01)  # PUB0 - ZK0
    assert out["anti_predator"].point == pytest.approx(0.4, abs=0.01)  # (1.5-1.0) - (0.8-0.7)


def test_h3a_ratio_of_leakages() -> None:
    # leakage PUB = 1 - 80/100 = 0.20, ZK = 1 - 85.5/90 = 0.05, so R = 0.25
    cells = {h3.PUB0: {"pnl_forecaster": np.full(200, 100.0)}, h3.PUB1: {"pnl_forecaster": np.full(200, 80.0)},
             h3.ZK0: {"pnl_forecaster": np.full(200, 90.0)}, h3.ZK1: {"pnl_forecaster": np.full(200, 85.5)}}
    stats = h3.h3a_stats(cells)
    assert stats["L_PUB"].point == pytest.approx(0.20)
    assert stats["L_ZK"].point == pytest.approx(0.05)
    assert stats["R"].point == pytest.approx(0.25)
    assert h3.h3a_verdict(stats["R"]) == SUPPORTED
