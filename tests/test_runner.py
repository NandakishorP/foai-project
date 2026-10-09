import hashlib
from pathlib import Path

import yaml

from tfs.experiments.runner import run_experiment

from .conftest import CONFIG_DIR


def _tiny_experiment(tmp_path: Path) -> Path:
    exp = {
        "extends": str(CONFIG_DIR / "base.yaml"),
        "name": "tiny",
        "seeds": {"count": 4, "start": 0},
        "season": {"n_markets": 2},
        "market": {"ticks": 120},
        "sweep": {"one_at_a_time": {"market.b_main": [50.0]}},
    }
    path = tmp_path / "tiny.yaml"
    path.write_text(yaml.safe_dump(exp))
    return path


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_runner_writes_outputs_with_cis(tmp_path: Path) -> None:
    result = run_experiment(_tiny_experiment(tmp_path), out_root=tmp_path / "out", workers=1)
    for name in ("runs.csv", "summary.csv", "per_market.csv", "config.yaml", "meta.json"):
        assert (result.out_dir / name).exists()
    assert len(result.summary) == 2  # baseline + one b value
    row = result.summary[0]
    assert row["truth_rms_lo"] <= row["truth_rms"] <= row["truth_rms_hi"]
    assert row["n_seeds"] == 4
    assert {r["market"] for r in result.per_market} == {0, 1}


def test_same_seeds_give_identical_csvs_serial_and_parallel(tmp_path: Path) -> None:
    cfg = _tiny_experiment(tmp_path)
    serial = run_experiment(cfg, out_root=tmp_path / "serial", workers=1)
    parallel = run_experiment(cfg, out_root=tmp_path / "parallel", workers=2)
    for name in ("runs.csv", "summary.csv", "per_market.csv"):
        assert _digest(serial.out_dir / name) == _digest(parallel.out_dir / name)
