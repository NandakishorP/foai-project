"""Every branch of the pre-registered H1/H2 rules, and the paired analysis on a tiny real experiment."""

from pathlib import Path

import yaml

from tfs.experiments.runner import run_experiment
from tfs.experiments.verdicts import CONTRADICTED, PARTLY, SUPPORTED, h1_verdict, h2_verdict
from tfs.metrics.paired import Interval

from .conftest import CONFIG_DIR


def iv(lo: float, hi: float) -> Interval:
    return Interval((lo + hi) / 2, lo, hi)


def test_h1_rules() -> None:
    assert h1_verdict(iv(0.35, 0.6), iv(-0.05, 0.10)) == SUPPORTED
    assert h1_verdict(iv(0.25, 0.6), iv(-0.05, 0.10)) == PARTLY  # L's CI dips below 0.30
    assert h1_verdict(iv(0.35, 0.6), iv(0.05, 0.20)) == PARTLY  # Δ1's CI crosses +15%
    assert h1_verdict(iv(0.35, 0.6), iv(0.31, 0.50)) == CONTRADICTED
    assert h1_verdict(iv(0.0, 0.1), iv(0.25, 0.40)) == PARTLY  # crosses +30%: not entirely above


def test_h2_rules() -> None:
    assert h2_verdict(iv(26, 40), iv(0.31, 0.6)) == SUPPORTED
    assert h2_verdict(iv(20, 40), iv(0.31, 0.6)) == PARTLY
    assert h2_verdict(iv(26, 40), iv(0.25, 0.6)) == PARTLY
    assert h2_verdict(iv(2, 9), iv(0.31, 0.6)) == CONTRADICTED  # no meaningful participation effect
    assert h2_verdict(iv(26, 40), iv(0.0, 0.15)) == CONTRADICTED  # truth lost barely moves


def test_analysis_pairs_twins_and_writes_a_verdict(tmp_path: Path) -> None:
    exp = {
        "extends": str(CONFIG_DIR / "base.yaml"),
        "name": "tiny_e2",
        "seeds": {"count": 3, "start": 0},
        "season": {"n_markets": 2},
        "market": {"ticks": 120},
        "analysis": {"hypothesis": "H1", "score_from_market": 1, "pair_on": "agents.predators.count",
                     "reference": {"agents.predators.count": 1}},
        "sweep": {"crossed": {"agents.predators.count": [0, 1]}},
    }
    path = tmp_path / "e.yaml"
    path.write_text(yaml.safe_dump(exp))
    result = run_experiment(path, out_root=tmp_path / "out", workers=1)
    assert result.verdict is not None
    assert result.verdict["verdict"] in (SUPPORTED, PARTLY, CONTRADICTED)
    assert result.verdict["scored_markets"] == "2-2"
    assert (result.out_dir / "paired.csv").exists() and (result.out_dir / "verdict.json").exists()
