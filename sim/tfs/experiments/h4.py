"""H4 verdict exactly as pre-registered (docs/PREREGISTRATION.md, H4; DECISIONS D-053, D-054).

Input: the per-run CSV of E4 (`results/e4/runs.csv`). All cells run seeds 0..199, so
statistics combining cells use a *joint* paired bootstrap: one resample of seed indices
applied to every cell (10,000 resamples, bootstrap seed 0). A threshold counts only if
the whole 95% CI clears it.

- P(s) = researchers' trading PnL per researcher-market under rule s, 1 predator.
- R4 = P(expectiminimax) / max over the four simple rules of P(s). The max is taken
  inside every resample, so choosing the best baseline is part of the statistic.
- L(s) = 1 − ΣPnL(s, 1 predator) / ΣPnL(s, 0 predators); ΔL = L(expectiminimax) − L(capped).
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np

from tfs.experiments.h3 import Cell, joint, load_cells
from tfs.experiments.verdicts import CONTRADICTED, PARTLY, SUPPORTED
from tfs.metrics.paired import Interval

SEARCH = "expectiminimax"
BASELINES = ("capped", "naive", "twap", "random")
RULES = BASELINES + (SEARCH,)
FIRST_MARKET = 5  # 0-based: markets 6-30, as H1
COLUMNS = {"pnl_forecaster": "sum", "pnl_per_researcher": "mean", "pnl_predator": "mean", "truth_mse": "mean",
           "forecaster_revert_share": "mean", "forecaster_unfilled_share": "mean", "frontruns": "mean"}


def label(rule: str, predators: int) -> str:
    return f"agents.forecasters.execution.rule={rule}|agents.predators.count={predators}|baseline"


# --------------------------------------------------------------------------- #
# The rule (literal)
# --------------------------------------------------------------------------- #


def h4_verdict(r4: Interval, delta_leakage: Interval) -> str:
    """Supported if CI(R4) >= 1.05 and CI(ΔL) < 0; contradicted if CI(R4) <= 1.00."""
    if r4.lo >= 1.05 and delta_leakage.hi < 0:
        return SUPPORTED
    if r4.hi <= 1.00:
        return CONTRADICTED
    return PARTLY


# --------------------------------------------------------------------------- #
# The statistics
# --------------------------------------------------------------------------- #


def r4_stat(cells: dict[str, Cell], predators: int) -> Interval:
    p = {rule: cells[label(rule, predators)]["pnl_per_researcher"] for rule in RULES}
    n = len(p[SEARCH])

    def stat(idx: np.ndarray) -> np.ndarray:
        best_baseline = np.max([p[rule][idx].mean(1) for rule in BASELINES], axis=0)
        return p[SEARCH][idx].mean(1) / best_baseline

    return joint(stat, n)


def leakage_stats(cells: dict[str, Cell]) -> dict[str, Interval]:
    """L(s) for every rule, and ΔL = L(expectiminimax) − L(capped)."""
    pnl = {(rule, k): cells[label(rule, k)]["pnl_forecaster"] for rule in RULES for k in (0, 1)}
    n = len(pnl[(SEARCH, 0)])

    def leak(rule: str, idx: np.ndarray) -> np.ndarray:
        return 1.0 - pnl[(rule, 1)][idx].sum(1) / pnl[(rule, 0)][idx].sum(1)

    out = {f"L_{rule}": joint(lambda idx, r=rule: leak(r, idx), n) for rule in RULES}
    out["delta_L"] = joint(lambda idx: leak(SEARCH, idx) - leak("capped", idx), n)
    return out


def describe(cells: dict[str, Cell]) -> dict[str, dict[str, float]]:
    """Seed-mean of every column per rule and predator count (descriptive)."""
    return {f"{rule}|pred={k}": {col: float(np.nanmean(cells[label(rule, k)][col])) for col in COLUMNS}
            for rule in RULES for k in (0, 1)}


def run(e4_dir: Path) -> dict[str, Any]:
    cells = load_cells(e4_dir / "runs.csv", FIRST_MARKET, COLUMNS)
    r4 = r4_stat(cells, 1)
    leak = leakage_stats(cells)
    verdict = h4_verdict(r4, leak["delta_L"])
    summary = {
        "rule": "docs/PREREGISTRATION.md, H4 (joint paired bootstrap over seeds, 10,000 resamples, seed 0)",
        "H4": {"verdict": verdict, "R4": asdict(r4), **{k: asdict(v) for k, v in leak.items()}},
        "descriptive": {"R4_zero_predators": asdict(r4_stat(cells, 0)), "cells": describe(cells)},
    }
    (e4_dir / "h4_verdict.json").write_text(
        json.dumps(summary, indent=2, default=lambda x: None if isinstance(x, float) and math.isnan(x) else x))
    return summary
