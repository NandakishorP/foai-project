"""Experiment runner: YAML config -> sweep points x seeds -> CSV results with 95% CIs.

Outputs in `results/<name>/`:
- `runs.csv`: one row per (sweep point, seed, market)
- `summary.csv`: one row per sweep point; metrics averaged within each run, then mean and CI across seeds
- `per_market.csv`: one row per (sweep point, market index); used for season charts
- `config.yaml`: the fully resolved raw config, including the sweep
- `meta.json`: git commit and settings, for provenance

Runs execute in parallel worker processes. Results are collected in task
order, so outputs are identical regardless of the number of workers.
"""

from __future__ import annotations

import csv
import json
import math
import os
import subprocess
from collections import defaultdict
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from tfs.core.config import SimConfig, SweepPoint, expand_sweep, load_raw
from tfs.core.types import Venue
from tfs.metrics.accuracy import brier_scores, decompose, time_to_epsilon
from tfs.metrics.stats import mean_ci, rms_ci
from tfs.simulation import MarketRecord, SeasonRecord, run_season

AGENT_KINDS = ("forecaster", "public_news", "noise", "arbitrageur", "trend", "predator")
MSE_METRICS = ("truth_mse", "aggregation_mse", "participation_mse")


# --------------------------------------------------------------------------- #
# One run -> rows
# --------------------------------------------------------------------------- #


def market_row(record: MarketRecord, season: SeasonRecord, epsilon: float) -> dict[str, Any]:
    """Flatten one market's measurements into a CSV row."""
    d = decompose(record.price_main, record.p_full, record.p_avail)
    brier_final, brier_mean = brier_scores(record.price_main, record.y)
    n_forecasters = len(season.traits)
    row: dict[str, Any] = {
        "seed": season.seed,
        "market": record.market,
        "y": record.y,
        "participation": len(record.researchers) / n_forecasters if n_forecasters else math.nan,
        "truth_mse": d.truth_mse,
        "aggregation_mse": d.aggregation_mse,
        "participation_mse": d.participation_mse,
        "cross_term": d.cross_term,
        "brier_final": brier_final,
        "brier_mean": brier_mean,
        "ref_truth_mse": float(np.mean((record.price_ref - record.p_full) ** 2)),
        # Benchmark for aggregation: the gap a price ignoring all research would have to p*_avail.
        "public_only_mse": float(np.mean((record.p_public - record.p_avail) ** 2)),
    }
    for k, ticks in enumerate(time_to_epsilon(record.price_main, record.p_avail, record.shock_ticks, epsilon)):
        row[f"time_to_eps_{k}"] = math.nan if ticks is None else ticks
        row[f"settled_{k}"] = 0.0 if ticks is None else 1.0  # share of runs that settle at all (with a CI)
    for kind in AGENT_KINDS:
        row[f"pnl_{kind}"] = sum(v for aid, v in record.pnl.items() if record.kinds[aid] == kind)
    costs = [season.traits[i].cost for i in record.researchers]
    row["research_cost"] = sum(c for c in costs if c is not None)
    row["mm_pnl_main"] = record.mm_pnl[Venue.MAIN]
    row["mm_pnl_ref"] = record.mm_pnl[Venue.REF]
    row["builder_revenue"] = record.builder_revenue
    # crowding (F-002): share of informed trades that revert, mostly on their own limits
    attempts = record.attempts_by_kind.get("forecaster", 0)
    row["forecaster_revert_share"] = record.reverts_by_kind.get("forecaster", 0) / attempts if attempts else math.nan
    row["frontruns"] = record.frontruns
    row["victim_reverts"] = record.victim_reverts
    row["executed"] = record.executed
    row["reverted"] = record.reverted
    return row


@dataclass(frozen=True)
class RunResult:
    rows: list[dict[str, Any]]
    forecaster_gross_pnl: list[float]  # every researching forecaster's PnL in every market (for cost calibration)


def run_one(cfg: SimConfig, seed: int) -> RunResult:
    """Worker entry point: one season (one master seed) of one configuration."""
    season = run_season(cfg, seed)
    rows = [market_row(m, season, cfg.metrics.epsilon) for m in season.markets]
    pnls = [v for m in season.markets for v in m.forecaster_pnl().values()]
    return RunResult(rows=rows, forecaster_gross_pnl=pnls)


def _run_task(task: tuple[SimConfig, int]) -> RunResult:
    return run_one(*task)


def run_points(points: Sequence[SweepPoint], seeds: Sequence[int], workers: int | None) -> list[list[RunResult]]:
    """Run every (point, seed); returns results[point_index][seed_index] in a fixed order."""
    tasks = [(p.config, s) for p in points for s in seeds]
    if workers == 1:
        flat = [_run_task(t) for t in tasks]
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            flat = list(pool.map(_run_task, tasks, chunksize=max(1, len(tasks) // (8 * (workers or os.cpu_count() or 1)))))
    n = len(seeds)
    return [flat[i * n : (i + 1) * n] for i in range(len(points))]


# --------------------------------------------------------------------------- #
# Aggregation across seeds
# --------------------------------------------------------------------------- #


def _metric_names(rows: Sequence[dict[str, Any]]) -> list[str]:
    skip = {"seed", "market", "y"}
    return [k for k in rows[0] if k not in skip]


def _seed_mean(rows: Sequence[dict[str, Any]], name: str) -> float:
    """Average of a metric over one seed's markets, skipping missing (NaN) values."""
    values = [r[name] for r in rows if not math.isnan(r[name])]
    return float(np.mean(values)) if values else math.nan


def summarise(rows_by_seed: Sequence[Sequence[dict[str, Any]]]) -> dict[str, Any]:
    """Average each metric within each seed (over its markets), then mean and 95% CI across seeds.

    MSE metrics are additionally reported as RMS. Time-to-epsilon also reports
    the censored share (runs that never settled).
    """
    names = _metric_names(rows_by_seed[0])
    per_seed = {name: [_seed_mean(rows, name) for rows in rows_by_seed] for name in names}
    out: dict[str, Any] = {"n_seeds": len(rows_by_seed)}
    for name in names:
        e = mean_ci(per_seed[name])
        out[f"{name}"], out[f"{name}_lo"], out[f"{name}_hi"] = e.mean, e.lo, e.hi
        if name.startswith("time_to_eps"):
            censored = [math.isnan(r[name]) for rows in rows_by_seed for r in rows]
            out[f"{name}_censored"] = float(np.mean(censored))
    for name in MSE_METRICS:
        e = rms_ci(per_seed[name])
        rms_name = name.replace("_mse", "_rms")
        out[rms_name], out[f"{rms_name}_lo"], out[f"{rms_name}_hi"] = e.mean, e.lo, e.hi
    share = research_share_priced(per_seed["aggregation_mse"], per_seed["public_only_mse"])
    out["research_captured"], out["research_captured_num"], out["research_captured_den"] = share
    return out


def research_share_priced(
    aggregation_mse: Sequence[float], public_only_mse: Sequence[float]
) -> tuple[float, float, float]:
    """Share of the acquired research information that the price reflects, with its parts.

    share = 1 − Σ (p − p*_avail)² / Σ (p_public − p*_avail)², pooled over all runs
    (a ratio of sums, not a mean of per-run ratios: single runs can have a tiny
    denominator). 1 means the price matches p*_avail; 0 means it is no closer
    than a price that ignores all research; negative means further away.
    Returns (share, numerator, denominator), with numerator and denominator as
    mean MSEs, so they can always be reported alongside the share (D-029).
    """
    numerator = float(np.mean(aggregation_mse))
    denominator = float(np.mean(public_only_mse))
    share = 1.0 - numerator / denominator if denominator > 0 else math.nan
    return share, numerator, denominator


def summarise_per_market(rows_by_seed: Sequence[Sequence[dict[str, Any]]]) -> list[dict[str, Any]]:
    """For season experiments: mean and CI across seeds for each market index."""
    by_market: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for rows in rows_by_seed:
        for r in rows:
            by_market[r["market"]].append(r)
    out = []
    for market in sorted(by_market):
        rows = by_market[market]
        entry: dict[str, Any] = {"market": market}
        for name in ("participation", *MSE_METRICS, "brier_mean"):
            e = mean_ci(r[name] for r in rows)
            entry[name], entry[f"{name}_lo"], entry[f"{name}_hi"] = e.mean, e.lo, e.hi
        out.append(entry)
    return out


# --------------------------------------------------------------------------- #
# Whole experiment
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ExperimentResult:
    name: str
    out_dir: Path
    points: list[SweepPoint]
    summary: list[dict[str, Any]]
    per_market: list[dict[str, Any]]
    results: list[list[RunResult]]
    verdict: dict[str, Any] | None = None  # set when the config has an `analysis:` section


def _git_state() -> dict[str, Any]:
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], capture_output=True, text=True, check=False).stdout.strip()

    return {"commit": git("rev-parse", "HEAD"), "dirty": bool(git("status", "--porcelain"))}


def _write_csv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    if not rows:
        return
    fields = list(rows[0])
    for r in rows[1:]:
        fields += [k for k in r if k not in fields]
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def run_experiment(
    config_path: Path,
    out_root: Path = Path("results"),
    workers: int | None = None,
    n_seeds: int | None = None,
) -> ExperimentResult:
    raw = load_raw(config_path)
    analysis = raw.get("analysis")
    points = expand_sweep(raw)
    seeds_cfg = points[0].config.seeds
    count = n_seeds if n_seeds is not None else seeds_cfg.count
    seeds = list(range(seeds_cfg.start, seeds_cfg.start + count))

    results = run_points(points, seeds, workers)

    name = points[0].config.name
    out_dir = out_root / name
    out_dir.mkdir(parents=True, exist_ok=True)

    run_rows, summary, per_market = [], [], []
    for point, point_results in zip(points, results):
        labels = {"point": point.label, **point.params}
        rows_by_seed = [r.rows for r in point_results]
        run_rows += [{**labels, **row} for rows in rows_by_seed for row in rows]
        summary.append({**labels, **summarise(rows_by_seed)})
        per_market += [{**labels, **row} for row in summarise_per_market(rows_by_seed)]

    _write_csv(out_dir / "runs.csv", run_rows)
    _write_csv(out_dir / "summary.csv", summary)
    _write_csv(out_dir / "per_market.csv", per_market)
    (out_dir / "config.yaml").write_text(yaml.safe_dump(raw, sort_keys=False))
    meta = {"git": _git_state(), "seeds": [seeds[0], seeds[-1]], "n_points": len(points), "config": str(config_path)}
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2))
    verdict = None
    if analysis is not None:
        from tfs.experiments.verdicts import analyse  # imported here: verdicts imports this module

        verdict = analyse(points, results, analysis, out_dir)
    return ExperimentResult(name, out_dir, points, summary, per_market, results, verdict)
