"""Hypothesis verdicts exactly as pre-registered (docs/PREREGISTRATION.md), plus the paired analysis feeding them.

The rule functions are deliberately tiny and literal, so they can be checked
line by line against PREREGISTRATION.md. A threshold counts as cleared only if
the whole 95% CI clears it (rule 3).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np

from tfs.core.config import SweepPoint
from tfs.experiments.runner import RunResult, _write_csv
from tfs.metrics.paired import Interval, leakage_ratio, mean_difference, participation_gap, rms_change

SUPPORTED, PARTLY, CONTRADICTED = "supported", "partly supported", "contradicted"


def h1_verdict(leakage: Interval, delta: Interval) -> str:
    """H1 (E2a): supported if CI(L) ≥ 0.30 and CI(Δ1) ≤ +15%; contradicted if CI(Δ1) > +30%; else partly."""
    if leakage.lo >= 0.30 and delta.hi <= 0.15:
        return SUPPORTED
    if delta.lo > 0.30:
        return CONTRADICTED
    return PARTLY


def h2_verdict(gap_pp: Interval, delta: Interval) -> str:
    """H2 (E2b): supported if CI(G) ≥ 25 pp and CI(Δ2) > +30%; contradicted if CI(G) < 10 pp or CI(Δ2) ≤ +15%."""
    if gap_pp.lo >= 25.0 and delta.lo > 0.30:
        return SUPPORTED
    if gap_pp.hi < 10.0 or delta.hi <= 0.15:
        return CONTRADICTED
    return PARTLY


# --------------------------------------------------------------------------- #
# Paired analysis of an experiment
# --------------------------------------------------------------------------- #


def _per_seed(results: Sequence[RunResult], first_market: int, column: str, how: str) -> np.ndarray:
    """One value per seed over the scored markets: their mean or their sum."""
    reduce = np.mean if how == "mean" else np.sum
    return np.array([reduce([r[column] for r in run.rows if r["market"] >= first_market]) for run in results])


def _twin_index(points: Sequence[SweepPoint], i: int, pair_on: str) -> int | None:
    target = {**points[i].params, pair_on: 0}
    for j, p in enumerate(points):
        if p.params == target:
            return j
    return None


def analyse(points: Sequence[SweepPoint], results: Sequence[Sequence[RunResult]], analysis: dict[str, Any],
            out_dir: Path) -> dict[str, Any]:
    """Pair every predator point with its zero-predator twin; write paired.csv and verdict.json."""
    pair_on = analysis["pair_on"]
    first = int(analysis["score_from_market"])
    rows = []
    for i, point in enumerate(points):
        if point.params.get(pair_on, 0) == 0:
            continue
        j = _twin_index(points, i, pair_on)
        if j is None:
            raise ValueError(f"no zero-predator twin for {point.label}")
        pred, base = results[i], results[j]
        stats = {
            "delta_truth_rms": rms_change(_per_seed(pred, first, "truth_mse", "mean"),
                                          _per_seed(base, first, "truth_mse", "mean")),
            "leakage": leakage_ratio(_per_seed(pred, first, "pnl_forecaster", "sum"),
                                     _per_seed(base, first, "pnl_forecaster", "sum")),
            "participation_gap_pp": participation_gap(_per_seed(base, first, "participation", "mean"),
                                                      _per_seed(pred, first, "participation", "mean")),
        }
        descriptive = {
            name: mean_difference(_per_seed(pred, first, name, "mean"), _per_seed(base, first, name, "mean"))
            for name in ("aggregation_mse", "participation_mse", "pnl_noise", "pnl_forecaster")
        }
        row: dict[str, Any] = {"point": point.label, "twin": points[j].label, **point.params}
        for name, iv in {**stats, **{f"diff_{k}": v for k, v in descriptive.items()}}.items():
            row[name], row[f"{name}_lo"], row[f"{name}_hi"] = iv.point, iv.lo, iv.hi
        for name in ("pnl_predator", "builder_revenue", "frontruns", "victim_reverts", "pnl_forecaster"):
            row[f"{name}_per_market"] = float(_per_seed(pred, first, name, "mean").mean())
        row["pnl_forecaster_per_market_base"] = float(_per_seed(base, first, "pnl_forecaster", "mean").mean())
        rows.append((point, stats, row))

    _write_csv(out_dir / "paired.csv", [r for _, _, r in rows])

    reference = analysis["reference"]
    matches = [(p, s) for p, s, _ in rows if all(p.params.get(k) == v for k, v in reference.items())]
    if len(matches) != 1:
        raise ValueError(f"reference {reference} must match exactly one point, found {len(matches)}")
    point, stats = matches[0]
    hypothesis = analysis["hypothesis"]
    if hypothesis == "H1":
        verdict = h1_verdict(stats["leakage"], stats["delta_truth_rms"])
    elif hypothesis == "H2":
        verdict = h2_verdict(stats["participation_gap_pp"], stats["delta_truth_rms"])
    else:
        raise ValueError(f"unknown hypothesis {hypothesis!r}")
    summary = {
        "hypothesis": hypothesis,
        "verdict": verdict,
        "reference_point": point.label,
        "scored_markets": f"{first + 1}-{point.config.season.n_markets}",
        "statistics": {k: asdict(v) for k, v in stats.items()},
        "rule": "docs/PREREGISTRATION.md (strict CI rule; paired bootstrap, 10,000 resamples, seed 0)",
    }
    (out_dir / "verdict.json").write_text(json.dumps(summary, indent=2))
    return summary
