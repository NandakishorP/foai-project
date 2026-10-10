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


def _per_seed(results: Sequence[RunResult], window: tuple[int, int], column: str, how: str) -> np.ndarray:
    """One value per seed over the markets in `window` (0-based, inclusive): their mean or their sum."""
    reduce = np.nanmean if how == "mean" else np.nansum
    first, last = window
    return np.array([reduce([r[column] for r in run.rows if first <= r["market"] <= last]) for run in results])


def _twin_index(points: Sequence[SweepPoint], i: int, pair_on: str) -> int | None:
    target = {**points[i].params, pair_on: 0}
    for j, p in enumerate(points):
        if p.params == target:
            return j
    return None


def _paired_row(point: SweepPoint, twin: SweepPoint, pred: Sequence[RunResult], base: Sequence[RunResult],
                window: tuple[int, int]) -> tuple[dict[str, Interval], dict[str, Any]]:
    stats = {
        "delta_truth_rms": rms_change(_per_seed(pred, window, "truth_mse", "mean"),
                                      _per_seed(base, window, "truth_mse", "mean")),
        "leakage": leakage_ratio(_per_seed(pred, window, "pnl_forecaster", "sum"),
                                 _per_seed(base, window, "pnl_forecaster", "sum")),
        "participation_gap_pp": participation_gap(_per_seed(base, window, "participation", "mean"),
                                                  _per_seed(pred, window, "participation", "mean")),
    }
    descriptive = {
        name: mean_difference(_per_seed(pred, window, name, "mean"), _per_seed(base, window, name, "mean"))
        for name in ("aggregation_mse", "participation_mse", "pnl_noise", "pnl_forecaster", "forecaster_revert_share")
    }
    row: dict[str, Any] = {"point": point.label, "twin": twin.label, "window": f"{window[0] + 1}-{window[1] + 1}",
                           **point.params}
    for name, iv in {**stats, **{f"diff_{k}": v for k, v in descriptive.items()}}.items():
        row[name], row[f"{name}_lo"], row[f"{name}_hi"] = iv.point, iv.lo, iv.hi
    for name in ("pnl_predator", "builder_revenue", "frontruns", "victim_reverts", "pnl_forecaster",
                 "participation", "forecaster_revert_share"):
        row[f"{name}_per_market"] = float(np.nanmean(_per_seed(pred, window, name, "mean")))
        row[f"{name}_per_market_base"] = float(np.nanmean(_per_seed(base, window, name, "mean")))
    return stats, row


def analyse(points: Sequence[SweepPoint], results: Sequence[Sequence[RunResult]], analysis: dict[str, Any],
            out_dir: Path) -> dict[str, Any]:
    """Pair every predator point with its zero-predator twin; write paired.csv and verdict.json.

    With `hypothesis: null` the analysis is EXPLORATORY: it writes paired.csv
    and exploratory.json for every window in `windows`, and never a verdict.
    """
    pair_on = analysis["pair_on"]
    last_market = points[0].config.season.n_markets - 1
    windows = [tuple(w) for w in analysis.get("windows") or [[int(analysis["score_from_market"]), last_market]]]
    scored: list[tuple[SweepPoint, dict[str, Interval]]] = []
    rows = []
    for i, point in enumerate(points):
        if point.params.get(pair_on, 0) == 0:
            continue
        j = _twin_index(points, i, pair_on)
        if j is None:
            raise ValueError(f"no zero-predator twin for {point.label}")
        for k, window in enumerate(windows):
            stats, row = _paired_row(point, points[j], results[i], results[j], window)
            rows.append(row)
            if k == 0:
                scored.append((point, stats))
    _write_csv(out_dir / "paired.csv", rows)

    hypothesis = analysis.get("hypothesis")
    if hypothesis is None:
        note = analysis.get("note")  # e.g. E3: verdicts come from a separate pre-registered analysis
        summary = {"note" if note else "EXPLORATORY": note or "not pre-registered; never alters a verdict (DECISIONS D-037/D-039)",
                   "windows": [f"{a + 1}-{b + 1}" for a, b in windows], "points": len(scored)}
        (out_dir / ("analysis.json" if note else "exploratory.json")).write_text(json.dumps(summary, indent=2))
        return summary

    reference = analysis["reference"]
    matches = [(p, s) for p, s in scored if all(p.params.get(k) == v for k, v in reference.items())]
    if len(matches) != 1:
        raise ValueError(f"reference {reference} must match exactly one point, found {len(matches)}")
    point, stats = matches[0]
    if hypothesis == "H1":
        verdict = h1_verdict(stats["leakage"], stats["delta_truth_rms"])
    elif hypothesis == "H2":
        verdict = h2_verdict(stats["participation_gap_pp"], stats["delta_truth_rms"])
    else:
        raise ValueError(f"unknown hypothesis {hypothesis!r}")
    first, last = windows[0]
    summary = {
        "hypothesis": hypothesis,
        "verdict": verdict,
        "reference_point": point.label,
        "scored_markets": f"{first + 1}-{last + 1}",
        "statistics": {k: asdict(v) for k, v in stats.items()},
        "rule": "docs/PREREGISTRATION.md (strict CI rule; paired bootstrap, 10,000 resamples, seed 0)",
    }
    (out_dir / "verdict.json").write_text(json.dumps(summary, indent=2))
    return summary
