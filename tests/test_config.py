from pathlib import Path

import pytest
import yaml

from tfs.core.config import ConfigError, SimConfig, build, expand_sweep, load_raw, replace_in

from .conftest import CONFIG_DIR


def test_base_config_loads(base_config: SimConfig) -> None:
    assert base_config.market.ticks > 0
    assert base_config.agents.belief_model in ("own_signals", "price_anchored")
    assert isinstance(base_config.information.shocks, tuple)


def test_unknown_key_is_rejected() -> None:
    raw = load_raw(CONFIG_DIR / "base.yaml")
    raw["agents"]["forecasters"]["kely_fraction"] = 0.5  # typo
    with pytest.raises(ConfigError, match="kely_fraction"):
        build(SimConfig, raw)


def test_missing_key_is_rejected() -> None:
    raw = load_raw(CONFIG_DIR / "base.yaml")
    del raw["market"]["b_ref"]
    with pytest.raises(ConfigError, match="b_ref"):
        build(SimConfig, raw)


def test_wrong_type_is_rejected() -> None:
    raw = load_raw(CONFIG_DIR / "base.yaml")
    raw["market"]["ticks"] = "many"
    with pytest.raises(ConfigError, match="ticks"):
        build(SimConfig, raw)


def test_endogenous_research_requires_cost(base_config: SimConfig) -> None:
    with pytest.raises(ConfigError, match="cost_median"):
        replace_in(base_config, "agents.forecasters.research.mode", "endogenous")


def test_extends_and_sweep_expansion(tmp_path: Path) -> None:
    exp = {
        "extends": str(CONFIG_DIR / "base.yaml"),
        "name": "test_sweep",
        "sweep": {
            "crossed": {"agents.belief_model": ["own_signals", "price_anchored"]},
            "one_at_a_time": {
                "agents.forecasters.count": [5, 10, 20],  # 10 is the baseline -> skipped
                "market.b_main": [30.0],
            },
        },
    }
    path = tmp_path / "exp.yaml"
    path.write_text(yaml.safe_dump(exp))
    points = expand_sweep(load_raw(path))

    # per belief model: baseline + 2 forecaster counts + 1 b value = 4
    assert len(points) == 8
    labels = [p.label for p in points]
    assert len(set(labels)) == len(labels)
    for p in points:
        assert p.config.name == "test_sweep"
        assert set(p.params) == {"agents.belief_model", "agents.forecasters.count", "market.b_main"}
        assert p.params["agents.forecasters.count"] == p.config.agents.forecasters.count
    counts = sorted(p.config.agents.forecasters.count for p in points if p.params["agents.belief_model"] == "own_signals")
    assert counts == [5, 10, 10, 20]


def test_sweep_rejects_unknown_parameter(tmp_path: Path) -> None:
    raw = load_raw(CONFIG_DIR / "base.yaml")
    raw["sweep"] = {"one_at_a_time": {"market.nonexistent": [1]}}
    with pytest.raises(ConfigError, match="nonexistent"):
        expand_sweep(raw)
