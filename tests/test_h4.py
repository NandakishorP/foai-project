"""H4 rule (every branch) and its statistics on synthetic per-seed data."""

import numpy as np
import pytest

from tfs.experiments import h4
from tfs.experiments.verdicts import CONTRADICTED, PARTLY, SUPPORTED
from tfs.metrics.paired import Interval


def iv(lo: float, hi: float) -> Interval:
    return Interval((lo + hi) / 2, lo, hi)


def test_h4_rules() -> None:
    assert h4.h4_verdict(iv(1.06, 1.2), iv(-0.05, -0.01)) == SUPPORTED
    assert h4.h4_verdict(iv(1.06, 1.2), iv(-0.05, 0.01)) == PARTLY  # leakage not clearly lower
    assert h4.h4_verdict(iv(1.01, 1.2), iv(-0.05, -0.01)) == PARTLY  # gain below 5%
    assert h4.h4_verdict(iv(0.90, 1.00), iv(-0.05, -0.01)) == CONTRADICTED


def _cells(pnl: dict[tuple[str, int], float], n: int = 200) -> dict:
    rng = np.random.default_rng(0)
    cells = {}
    for (rule, k), v in pnl.items():
        per_seed = v + rng.normal(0, 0.01, n)
        cells[h4.label(rule, k)] = {"pnl_per_researcher": per_seed, "pnl_forecaster": 10 * per_seed}
    return cells


def test_r4_divides_by_the_best_baseline() -> None:
    pnl = {(r, k): 5.0 for r in h4.RULES for k in (0, 1)}
    pnl[("naive", 1)] = 6.0  # the best simple rule
    pnl[("expectiminimax", 1)] = 6.6
    r4 = h4.r4_stat(_cells(pnl), 1)
    assert r4.point == pytest.approx(1.10, abs=0.01)


def test_leakage_is_measured_against_each_rules_own_twin() -> None:
    pnl = {(r, k): 5.0 for r in h4.RULES for k in (0, 1)}
    pnl[("capped", 1)] = 4.0  # capped loses 20%
    pnl[("expectiminimax", 1)] = 4.5  # search loses 10%
    stats = h4.leakage_stats(_cells(pnl))
    assert stats["L_capped"].point == pytest.approx(0.2, abs=0.01)
    assert stats["L_expectiminimax"].point == pytest.approx(0.1, abs=0.01)
    assert stats["delta_L"].point == pytest.approx(-0.1, abs=0.01)
