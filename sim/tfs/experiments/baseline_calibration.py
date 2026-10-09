"""Calibration of the no-predator baseline (DECISIONS D-026, revised by D-029).

Chooses rho (research-signal correlation), informed capital (bankroll / b) and
the research-cost median so that, without predators, (a) the market prices at
least 60% of the research information and (b) steady-state participation is
50–70%. The rule is fixed in DECISIONS before any run. This module only
executes it. It calibrates the baseline before predators exist; it does not
tune hypothesis outcomes.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np

from tfs.core.config import SimConfig, SweepPoint, replace_in
from tfs.experiments.runner import RunResult, _write_csv, research_share_priced, run_points

RHO_GRID = (0.0, 0.25, 0.5, 0.75, 0.9, 1.0)
CAPITAL_RATIOS = (1.0, 2.0, 4.0)  # bankroll / b_main; = bankrolls {100, 200, 400} at b_main = 100
COST_MULTIPLIERS = (0.25, 0.5, 0.75, 1.0)
CAPTURED_MIN = 0.6
PARTICIPATION_BAND = (0.5, 0.7)
PARTICIPATION_TARGET = 0.6
STEADY_STATE_FIRST_MARKET = 20  # markets 21–30 (0-based index 20..29)
SEASON_MARKETS = 30


@dataclass(frozen=True)
class GridPoint:
    rho: float
    capital_ratio: float
    cost_unit: float  # M: median gross profit of a researching forecaster at full participation (D-017 procedure)
    multiplier: float
    cost_median: float
    participation: float  # steady-state mean
    share_priced: float  # steady-state share of research information priced (pooled)
    share_num: float  # mean aggregation MSE (numerator)
    share_den: float  # mean public-only MSE (denominator)

    def in_band(self) -> bool:
        return PARTICIPATION_BAND[0] <= self.participation <= PARTICIPATION_BAND[1]

    def feasible(self) -> bool:
        return self.share_priced >= CAPTURED_MIN and self.in_band()


def _with(base: SimConfig, rho: float, capital_ratio: float) -> SimConfig:
    cfg = replace_in(base, "information.private.rho", rho)
    return replace_in(cfg, "agents.forecasters.capital_ratio", capital_ratio)


def cost_unit(base: SimConfig, seeds: Sequence[int], workers: int | None) -> float:
    """D-017 procedure: median gross profit per researched market, everyone researching, single markets."""
    cfg = replace_in(replace_in(base, "agents.forecasters.research.mode", "always"), "season.n_markets", 1)
    [results] = run_points([SweepPoint("cost unit", {}, cfg)], seeds, workers)
    return float(np.median([p for run in results for p in run.forecaster_gross_pnl]))


def steady_state(results: Sequence[RunResult]) -> tuple[float, tuple[float, float, float]]:
    """(mean participation, (share priced, numerator, denominator)) over markets 21–30 of every seed."""
    rows = [r for run in results for r in run.rows if r["market"] >= STEADY_STATE_FIRST_MARKET]
    participation = float(np.mean([r["participation"] for r in rows]))
    share = research_share_priced([r["aggregation_mse"] for r in rows], [r["public_only_mse"] for r in rows])
    return participation, share


def season_config(cfg: SimConfig, cost_median: float) -> SimConfig:
    cfg = replace_in(cfg, "season.n_markets", SEASON_MARKETS)
    cfg = replace_in(cfg, "agents.forecasters.research.cost_median", cost_median)
    return replace_in(cfg, "agents.forecasters.research.mode", "endogenous")


def preference_key(g: GridPoint) -> tuple[float, float, float]:
    """D-029 (c): smallest rho, then smallest bankroll/b, then participation closest to 60%."""
    return (g.rho, g.capital_ratio, abs(g.participation - PARTICIPATION_TARGET))


def select(grid: Sequence[GridPoint]) -> tuple[GridPoint | None, str]:
    feasible = [g for g in grid if g.feasible()]
    if feasible:
        return min(feasible, key=preference_key), "feasible; preference order D-029 (c)"
    in_band = [g for g in grid if g.in_band()]
    if in_band:
        # D-029 (d): highest share priced among in-band points; ties broken by the preference order
        best = max(in_band, key=lambda g: (g.share_priced, [-x for x in preference_key(g)]))
        return best, "FALLBACK D-029 (d): nothing feasible; highest share priced with participation in band (limitation)"
    return None, "no grid point has participation in the band; nothing to freeze"


def calibrate(base: SimConfig, seeds: Sequence[int], workers: int | None, out_dir: Path) -> dict[str, Any]:
    """Run the full D-029 grid, apply the selection rule, write grid.csv and choice.json."""
    grid: list[GridPoint] = []
    for rho in RHO_GRID:
        for capital in CAPITAL_RATIOS:
            cfg = _with(base, rho, capital)
            unit = cost_unit(cfg, seeds, workers)
            points = [SweepPoint(f"rho={rho} cap={capital} m={m}", {}, season_config(cfg, m * unit)) for m in COST_MULTIPLIERS]
            for m, results in zip(COST_MULTIPLIERS, run_points(points, seeds, workers)):
                participation, (share, num, den) = steady_state(results)
                grid.append(GridPoint(rho, capital, unit, m, m * unit, participation, share, num, den))

    choice, reason = select(grid)
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(out_dir / "grid.csv", [{**asdict(g), "feasible": g.feasible()} for g in grid])
    summary = {
        "rule": "DECISIONS D-029",
        "choice": None if choice is None else {**asdict(choice), "feasible": choice.feasible()},
        "reason": reason,
        "n_seeds": len(seeds),
    }
    (out_dir / "choice.json").write_text(json.dumps(summary, indent=2))
    return summary
