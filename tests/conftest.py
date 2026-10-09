"""Shared test fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from tfs.core.config import SimConfig, load_config

CONFIG_DIR = Path(__file__).resolve().parents[1] / "sim" / "experiments" / "configs"


@pytest.fixture
def base_config() -> SimConfig:
    return load_config(CONFIG_DIR / "base.yaml")
