"""Shock scenarios (Topic 6 market stability; DECISIONS D-053). Descriptive: no verdicts.

For every sweep point of a scenario config and every seed, one market is run. Around each
event (shock, correction, depeg start) we compute the stability metrics of
tfs.metrics.stability and keep the price paths and order flows, aligned on the event.

Outputs (results/<name>/):
- stability.csv: per point and event, the mean of each metric with a 95% bootstrap CI over seeds;
- amplification.csv: trend followers on (count 2) minus off (count 0), paired on seeds,
  per metric, with a 95% CI. This is the trend-follower amplification;
- event_<event>.png: mean paths of the main and reference prices, p*_avail and p*_full;
- flows_<event>.png: cumulative net order flow by agent kind. This is where trend
  followers and the arbitrageur are seen reacting.

Paths are flipped so the event always points up: for news, the direction p*_avail moved;
for a depeg, which carries no news, the outcome Y. Otherwise averaging over seeds would
cancel moves in opposite directions.
"""

from __future__ import annotations

import csv
import json
import math
import re
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, fields
from pathlib import Path

import numpy as np

from tfs.core.config import SimConfig, SweepPoint, expand_sweep, load_raw
from tfs.metrics.paired import Interval, paired_bootstrap
from tfs.metrics.stability import WINDOW, EventMetrics, direction, event_metrics, events
from tfs.simulation import MarketRecord, run_season

PRE = 20  # ticks shown before the event
FLOW_KINDS = ("forecaster", "public_news", "noise", "arbitrageur", "trend")
TREND = "agents.trend.count"


@dataclass(frozen=True)
class RunStudy:
    metrics: dict[str, EventMetrics]  # by event name
    paths: dict[str, dict[str, np.ndarray]]  # by event name: series of length PRE + WINDOW (NaN-padded)


def aligned_paths(record: MarketRecord, name: str, t0: int) -> dict[str, np.ndarray]:
    d = (1 if record.y == 1 else -1) if name == "depeg" else direction(record, t0)
    a, b = t0 - PRE, t0 + WINDOW
    lo, hi = max(0, a), min(len(record.price_main), b)

    def place(series: np.ndarray) -> np.ndarray:
        out = np.full(PRE + WINDOW, np.nan)
        out[lo - a:hi - a] = series[lo:hi]
        return out

    def flip(p: np.ndarray) -> np.ndarray:
        return p if d > 0 else 1.0 - p

    paths = {key: place(flip(series)) for key, series in
             (("main", record.price_main), ("reference", record.price_ref), ("p*_avail", record.p_avail),
              ("p*_full", record.p_full))}
    for kind in FLOW_KINDS:
        cumulative = np.cumsum(d * record.flow_main.get(kind, np.zeros(len(record.price_main))))
        paths[f"flow_{kind}"] = place(cumulative - (cumulative[lo - 1] if lo > 0 else 0.0))  # 0 at the window start
    return paths


def study_one(task: tuple[SimConfig, int, tuple[str, ...]]) -> RunStudy:
    """One market; metrics and paths for the events the scenario declares (`analysis.events`)."""
    cfg, seed, wanted = task
    record = run_season(cfg, seed).markets[0]
    found = events(record, cfg.market.depeg.start)  # the depeg window exists even in the δ = 0 control
    evs = {name: tick for name, tick in found.items() if name in wanted}
    return RunStudy({n: event_metrics(record, n, evs, cfg.metrics.epsilon) for n in evs},
                    {n: aligned_paths(record, n, t) for n, t in evs.items()})


def run_study(points: Sequence[SweepPoint], seeds: Sequence[int], wanted: tuple[str, ...],
              workers: int | None) -> list[list[RunStudy]]:
    tasks = [(p.config, s, wanted) for p in points for s in seeds]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        flat = list(pool.map(study_one, tasks, chunksize=max(1, len(tasks) // 64)))
    n = len(seeds)
    return [flat[i * n:(i + 1) * n] for i in range(len(points))]


# --------------------------------------------------------------------------- #
# Aggregation
# --------------------------------------------------------------------------- #

METRICS = [f.name for f in fields(EventMetrics)]


def _values(runs: Sequence[RunStudy], event: str, metric: str) -> np.ndarray:
    return np.array([getattr(r.metrics[event], metric) for r in runs])


def _mean_ci(x: np.ndarray) -> Interval:
    if np.all(np.isnan(x)):
        return Interval(math.nan, math.nan, math.nan)
    return Interval(*paired_bootstrap(lambda idx: np.nanmean(x[idx], axis=1), len(x)))


def _diff_ci(on: np.ndarray, off: np.ndarray) -> Interval:
    if np.all(np.isnan(on)) or np.all(np.isnan(off)):
        return Interval(math.nan, math.nan, math.nan)
    return Interval(*paired_bootstrap(lambda idx: np.nanmean(on[idx], axis=1) - np.nanmean(off[idx], axis=1),
                                      len(on)))


def _twin(points: Sequence[SweepPoint], i: int) -> int | None:
    """The point identical to points[i] except with no trend followers."""
    target = {**points[i].params, TREND: 0}
    return next((j for j, p in enumerate(points) if p.params == target and j != i), None)


def summarise(points: Sequence[SweepPoint], results: list[list[RunStudy]]) -> tuple[list[dict], list[dict]]:
    stability, amplification = [], []
    for i, (point, runs) in enumerate(zip(points, results)):
        for event in runs[0].metrics:
            row = {"point": point.label, "event": event}
            for m in METRICS:
                iv = _mean_ci(_values(runs, event, m))
                row[m], row[f"{m}_lo"], row[f"{m}_hi"] = iv.point, iv.lo, iv.hi
            stability.append(row)
            j = _twin(points, i)
            if j is not None and point.params.get(TREND, 0) > 0:
                diff = {"point": point.label, "twin": points[j].label, "event": event}
                for m in METRICS:
                    iv = _diff_ci(_values(runs, event, m), _values(results[j], event, m))
                    diff[m], diff[f"{m}_lo"], diff[f"{m}_hi"] = iv.point, iv.lo, iv.hi
                amplification.append(diff)
    return stability, amplification


def short_label(label: str) -> str:
    """'information.shocks=[{'tick': 100, 'nats': 3.0, 'status': 'false'}]|agents.trend.count=2' -> 'shock 3.0 nats | trend 2'."""
    label = re.sub(r"information\.shocks=\[\{'tick': \d+, 'nats': ([\d.]+), 'status': '\w+'\}\]", r"shock \1 nats", label)
    for long, short in (("agents.trend.count=", "trend "), ("information.q_false=", "q_false "),
                        ("market.depeg.noise_withdrawal=", "noise away "), ("market.depeg.discount=", "depeg δ "),
                        ("mempool.policy=", ""), ("agents.whale.budget=", "whale budget "),
                        ("agents.arbitrageurs.count=", "arbs "), ("|baseline", "")):
        label = label.replace(long, short)
    return label.replace("|", " | ")


def _write(rows: list[dict], path: Path) -> None:
    if not rows:
        return
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def plot(points: Sequence[SweepPoint], results: list[list[RunStudy]], out: Path, title: str) -> list[Path]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    written = []
    ticks = np.arange(-PRE, WINDOW)
    for event in results[0][0].paths:
        for kind, keys in (("event", ("main", "reference", "p*_avail", "p*_full")),
                           ("flows", tuple(f"flow_{k}" for k in FLOW_KINDS))):
            n = len(points)
            cols = min(n, 4)
            rows = math.ceil(n / cols)
            fig, axes = plt.subplots(rows, cols, figsize=(4.2 * cols, 3.2 * rows), squeeze=False, sharey=True)
            for ax, point, runs in zip(axes.flat, points, results):
                for key in keys:
                    mean = np.nanmean([r.paths[event][key] for r in runs], axis=0)
                    ax.plot(ticks, mean, lw=2, label=key.removeprefix("flow_"))
                ax.axvline(0, color="grey", lw=1, ls=":")
                ax.set_title(short_label(point.label), fontsize=8)
                ax.grid(alpha=0.3)
            for ax in axes.flat[n:]:
                ax.axis("off")
            axes.flat[0].legend(frameon=False, fontsize=7)
            what = "mean price (event direction = up)" if kind == "event" else "cumulative net flow, shares (event direction = +)"
            fig.suptitle(f"{title}: {event} — {what}; ticks from the event", fontsize=10)
            fig.tight_layout()
            path = out / f"{kind}_{event}.png"
            fig.savefig(path, dpi=130)
            plt.close(fig)
            written.append(path)
    return written


def run(config: Path, seeds: int | None, workers: int | None, out_root: Path, git_state: dict) -> Path:
    raw = load_raw(config)
    points = expand_sweep(raw)
    n = seeds if seeds is not None else points[0].config.seeds.count
    seed_list = list(range(points[0].config.seeds.start, points[0].config.seeds.start + n))
    wanted = tuple(raw.get("analysis", {}).get("events", ()))
    results = run_study(points, seed_list, wanted, workers)
    out = out_root / raw["name"]
    out.mkdir(parents=True, exist_ok=True)
    stability, amplification = summarise(points, results)
    _write(stability, out / "stability.csv")
    _write(amplification, out / "amplification.csv")
    plot(points, results, out, raw["name"])
    (out / "meta.json").write_text(json.dumps({"git": git_state, "seeds": [seed_list[0], seed_list[-1]],
                                               "points": [p.label for p in points], "config": str(config),
                                               "window": WINDOW, "pre": PRE}, indent=2))
    return out
