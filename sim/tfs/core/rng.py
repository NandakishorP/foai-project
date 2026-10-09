"""Deterministic, named random streams derived from one master seed.

Every source of randomness in a run (outcome, each news stream, each agent,
the block builder) gets its own `numpy.random.Generator`. Streams are keyed by
*name*, not by the order in which they are created. This gives "common random
numbers" across experimental conditions: adding a predator, or changing how
many forecasters exist, does not change the noise traders' draws or the signals
of the forecasters that were already there. Comparisons between conditions
on the same seed are therefore paired, which lowers their variance.
"""

from __future__ import annotations

import zlib

import numpy as np


def _stable_id(name: str) -> int:
    """Map a component name to a stable integer.

    Python's built-in `hash()` of a string is randomised per process
    (PYTHONHASHSEED), so it would break reproducibility across runs and worker
    processes. CRC32 is fixed and fast; collisions are irrelevant at our scale
    because component names are a short, fixed list.
    """
    return zlib.crc32(name.encode("utf-8"))


class RngFactory:
    """Creates independent random generators for named simulation components."""

    def __init__(self, master_seed: int) -> None:
        if master_seed < 0:
            raise ValueError("master_seed must be non-negative")
        self.master_seed = master_seed

    def stream(self, component: str, market: int = 0, index: int = 0) -> np.random.Generator:
        """Return the generator for `component` in market `market`, instance `index`.

        The same (master_seed, component, market, index) always gives the same
        stream, regardless of which other streams have been created.
        """
        if market < 0 or index < 0:
            raise ValueError("market and index must be non-negative")
        seq = np.random.SeedSequence(
            entropy=self.master_seed,
            spawn_key=(_stable_id(component), market, index),
        )
        return np.random.Generator(np.random.PCG64(seq))
