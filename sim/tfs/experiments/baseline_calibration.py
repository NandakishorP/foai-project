"""Calibration of the no-predator baseline (DECISIONS D-026).

Chooses rho (research-signal correlation) and the research-cost median so that,
without predators, (a) the market prices at least 60% of the research
information and (b) steady-state participation is 50–70%. The rule is fixed in
D-026 before any run. This module only executes it. It is calibration of the
baseline, done before predators exist, not tuning of hypothesis outcomes.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np

from tfs.core.config import SimConfig, SweepPoint, replace_in
from tfs.experiments.runner import RunResult, _write_csv, run_points

RHO_GRID = (0.0, 0.25, 0.5, 0.75, 0.9, 1.0)
COST_MULTIPLIERS = (0.25, 0.5, 0.75, 1.0)
CAPTURED_MIN = 0.6
PARTICIPATION_BAND = (0.5, 0.7)
PARTICIPATION_TARGET = 0.6
STEADY_STATE_FIRST_MARKET = 20  # markets 21–30 (0-based index 20..29)
SEASON_MARKETS = 30
MAX_BISECTIONS = 6


@dataclass(frozen=True)
class GridPoint:
    rho: float
    cost_unit: float  # M(rho): median gross profit of a researching forecaster at full participation
    multiplier: float
    cost_median: float
    participation: float  # steady-state mean
    research_captured: float  # steady-state share of research information priced

    @property
    def feasible(self) -> bool:
        lo, hi = PARTICIPATION_BAND
        return self.research_captured >= CAPTURED_MIN and lo <= self.participation <= hi


def _point(cfg: SimConfig, label: str) -> SweepPoint:
    return SweepPoint(label=label, params={}, config=cfg)


def cost_unit(base: SimConfig, rho: float, seeds: Sequence[int], workers: int | None) -> float:
    """D-017 procedure at this rho: median gross profit per researched market, everyone researching."""
    cfg = replace_in(base, "information.private.rho", rho)
    cfg = replace_in(cfg, "agents.forecasters.research.mode", "always")
    cfg = replace_in(cfg, "season.n_markets", 1)
    [results] = run_points([_point(cfg, f"unit rho={rho}")], seeds, workers)
    return float(np.median([p for run in results for p in run.forecaster_gross_pnl]))


def steady_state(results: Sequence[RunResult]) -> tuple[float, float]:
    """(mean participation, research captured) over markets 21–30 of every seed."""
    rows = [r for run in results for r in run.rows if r["market"] >= STEADY_STATE_FIRST_MARKET]
    participation = float(np.mean([r["participation"] for r in rows]))
    aggregation = float(np.mean([r["aggregation_mse"] for r in rows]))
    public_only = float(np.mean([r["public_only_mse"] for r in rows]))
    return participation, 1.0 - aggregation / public_only


def season_config(base: SimConfig, rho: float, cost_median: float) -> SimConfig:
    cfg = replace_in(base, "information.private.rho", rho)
    cfg = replace_in(cfg, "season.n_markets", SEASON_MARKETS)
    cfg = replace_in(cfg, "agents.forecasters.research.cost_median", cost_median)
    return replace_in(cfg, "agents.forecasters.research.mode", "endogenous")


def evaluate(base: SimConfig, rho: float, unit: float, multipliers: Sequence[float],
             seeds: Sequence[int], workers: int | None) -> list[GridPoint]:
    points = [_point(season_config(base, rho, m * unit), f"rho={rho} m={m}") for m in multipliers]
    out = []
    for m, results in zip(multipliers, run_points(points, seeds, workers)):
        participation, captured = steady_state(results)
        out.append(GridPoint(rho, unit, m, m * unit, participation, captured))
    return out


def _bisect(base: SimConfig, low: GridPoint, high: GridPoint, seeds: Sequence[int],
            workers: int | None, log: list[GridPoint]) -> GridPoint | None:
    """Bisect the cost multiplier between two grid points whose participation brackets the band.

    Higher cost means lower participation, so `low` (cheaper) has participation above the band.
    """
    lo_m, hi_m = low.multiplier, high.multiplier
    for _ in range(MAX_BISECTIONS):
        mid = (lo_m + hi_m) / 2
        [point] = evaluate(base, low.rho, low.cost_unit, [mid], seeds, workers)
        log.append(point)
        if PARTICIPATION_BAND[0] <= point.participation <= PARTICIPATION_BAND[1]:
            return point
        if point.participation > PARTICIPATION_BAND[1]:
            lo_m = mid
        else:
            hi_m = mid
    return None


def calibrate(base: SimConfig, seeds: Sequence[int], workers: int | None, out_dir: Path) -> dict[str, Any]:
    """Run the full D-026 grid, apply the selection rule, write grid.csv and choice.json."""
    grid: list[GridPoint] = []
    for rho in RHO_GRID:
        unit = cost_unit(base, rho, seeds, workers)
        grid.extend(evaluate(base, rho, unit, COST_MULTIPLIERS, seeds, workers))

    choice: GridPoint | None = None
    reason = "no rho satisfies both criteria on the grid; nothing frozen (report to owner)"
    bisections: list[GridPoint] = []
    for rho in RHO_GRID:
        at_rho = sorted((g for g in grid if g.rho == rho), key=lambda g: g.multiplier)
        feasible = [g for g in at_rho if g.feasible]
        if feasible:
            choice = min(feasible, key=lambda g: abs(g.participation - PARTICIPATION_TARGET))
            reason = f"smallest feasible rho on the grid; multiplier closest to {PARTICIPATION_TARGET:.0%} participation"
            break
        # bracketing case: (a) holds at both neighbours, participation crosses the band between them
        for cheap, dear in zip(at_rho, at_rho[1:]):
            if (cheap.research_captured >= CAPTURED_MIN and dear.research_captured >= CAPTURED_MIN
                    and cheap.participation > PARTICIPATION_BAND[1] and dear.participation < PARTICIPATION_BAND[0]):
                found = _bisect(base, cheap, dear, seeds, workers, bisections)
                if found is not None and found.feasible:
                    choice = found
                    reason = "smallest rho where participation brackets the band; cost multiplier found by bisection"
                break
        if choice is not None:
            break

    out_dir.mkdir(parents=True, exist_ok=True)
    rows = [{**asdict(g), "feasible": g.feasible, "stage": "grid"} for g in grid]
    rows += [{**asdict(g), "feasible": g.feasible, "stage": "bisection"} for g in bisections]
    _write_csv(out_dir / "grid.csv", rows)
    summary = {
        "rule": "DECISIONS D-026",
        "choice": None if choice is None else {**asdict(choice), "feasible": choice.feasible},
        "reason": reason,
        "n_seeds": len(seeds),
    }
    (out_dir / "choice.json").write_text(json.dumps(summary, indent=2))
    return summary
