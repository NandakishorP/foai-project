"""E5: the cost of manipulation (SPEC §7; descriptive; measures fixed in DECISIONS D-059 before the run).

A whale backs the wrong outcome: from tick `start` it buys to hold the price of the outcome
that will happen at 0.30, until its budget is spent or the window ends. Every whale point
is paired, seed by seed, with a twin whose whale has budget 0 (never trades) and the same
number of arbitrageurs. The world is otherwise identical: same signals, same noise orders.

Per run, over the window [start, end + AFTER):
- deviation_ticks: Σ_t |price − p*_avail|, the excess over the twin is "deviation × duration";
- max_deviation: the largest |price − p*_avail|;
- ticks_off: ticks with |price − p*_avail| ≥ ε;
- correction_time: ticks from the whale's last trade until the price is within ε of
  p*_avail for good (AFTER if never): how fast informed traders and arbitrageurs undo it;
- whale_pnl: the whale's profit (negative = its loss);
- pnl_<kind>: profit by agent kind and the market makers'; the paired difference to the
  twin says who collected the whale's loss.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from tfs.core.config import SimConfig, SweepPoint, expand_sweep, load_raw
from tfs.core.types import Venue
from tfs.experiments.shock_study import _diff_ci, _mean_ci, _write
from tfs.simulation import run_season

AFTER = 60  # ticks after the window that still count
KINDS = ("forecaster", "public_news", "noise", "arbitrageur", "trend", "whale")
TWIN = "agents.whale.budget"


def study_one(task: tuple[SimConfig, int]) -> tuple[dict[str, float], np.ndarray]:
    cfg, seed = task
    w = cfg.agents.whale
    m = run_season(cfg, seed).markets[0]
    lo, hi = w.start, min(w.end + AFTER, len(m.price_main))
    gap = np.abs(m.price_main - m.p_avail)
    eps = cfg.metrics.epsilon
    whale_ticks = np.flatnonzero(m.volume_main.get("whale", np.zeros(len(gap))) > 0)
    last = int(whale_ticks[-1]) + 1 if whale_ticks.size else lo
    after = gap[last:hi] < eps
    if after.size == 0 or not after[-1]:
        correction = float(hi - last)
    else:
        outside = np.flatnonzero(~after)
        correction = 0.0 if outside.size == 0 else float(outside[-1] + 1)
    row = {
        "deviation_ticks": float(gap[lo:hi].sum()),
        "max_deviation": float(gap[lo:hi].max()),
        "ticks_off": float((gap[lo:hi] >= eps).sum()),
        "correction_time": correction,
        "whale_active_ticks": float(whale_ticks.size),
        "mm_main": m.mm_pnl[Venue.MAIN],
        "mm_ref": m.mm_pnl[Venue.REF],
    }
    for kind in KINDS:
        row[f"pnl_{kind}"] = sum(v for aid, v in m.pnl.items() if m.kinds[aid] == kind)
    profile = np.full(20 + w.end - w.start + AFTER, np.nan)  # |price − p*_avail| from start − 20
    a = w.start - 20
    seg = gap[max(a, 0):hi]
    profile[max(a, 0) - a:max(a, 0) - a + len(seg)] = seg
    return row, profile


def run(config: Path, seeds: int | None, workers: int | None, out_root: Path, git_state: dict) -> Path:
    raw = load_raw(config)
    points = expand_sweep(raw)
    n = seeds if seeds is not None else points[0].config.seeds.count
    seed_list = list(range(points[0].config.seeds.start, points[0].config.seeds.start + n))
    tasks = [(p.config, s) for p in points for s in seed_list]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        flat = list(pool.map(study_one, tasks, chunksize=max(1, len(tasks) // 64)))
    results = [flat[i * n:(i + 1) * n] for i in range(len(points))]
    out = out_root / raw["name"]
    out.mkdir(parents=True, exist_ok=True)
    summary, paired = summarise(points, results)
    _write(summary, out / "e5.csv")
    _write(paired, out / "e5_paired.csv")
    plot(points, results, out)
    (out / "meta.json").write_text(json.dumps({"git": git_state, "seeds": [seed_list[0], seed_list[-1]],
                                               "points": [p.label for p in points], "after": AFTER}, indent=2))
    return out


def summarise(points: Sequence[SweepPoint], results: list[list]) -> tuple[list[dict], list[dict]]:
    metrics = list(results[0][0][0])
    summary, paired = [], []
    for i, (point, runs) in enumerate(zip(points, results)):
        row = {"point": point.label}
        for m in metrics:
            iv = _mean_ci(np.array([r[0][m] for r in runs]))
            row[m], row[f"{m}_lo"], row[f"{m}_hi"] = iv.point, iv.lo, iv.hi
        summary.append(row)
        if point.params.get(TWIN, 0) > 0:
            j = next(k for k, p in enumerate(points) if p.params == {**point.params, TWIN: 0})
            diff = {"point": point.label, "twin": points[j].label}
            for m in metrics:
                iv = _diff_ci(np.array([r[0][m] for r in runs]), np.array([r[0][m] for r in results[j]]))
                diff[m], diff[f"{m}_lo"], diff[f"{m}_hi"] = iv.point, iv.lo, iv.hi
            paired.append(diff)
    return summary, paired


def plot(points: Sequence[SweepPoint], results: list[list], out: Path) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    arb_counts = sorted({p.params.get("agents.arbitrageurs.count") for p in points})
    fig, axes = plt.subplots(1, len(arb_counts), figsize=(6 * len(arb_counts), 3.8), sharey=True, squeeze=False)
    w = points[0].config.agents.whale
    ticks = np.arange(-20, w.end - w.start + AFTER)
    for ax, arbs in zip(axes[0], arb_counts):
        for point, runs in zip(points, results):
            if point.params.get("agents.arbitrageurs.count") != arbs:
                continue
            mean = np.nanmean([r[1] for r in runs], axis=0)
            ax.plot(ticks, mean, lw=2, label=f"budget {point.params[TWIN]:g}")
        ax.axvspan(0, w.end - w.start, color="grey", alpha=0.12, lw=0)
        ax.set_title(f"arbitrageurs: {arbs}", fontsize=10)
        ax.set_xlabel("ticks from the whale's start (shaded: its window)")
        ax.grid(alpha=0.3)
    axes[0][0].set_ylabel("mean |price − p*_avail|")
    axes[0][0].legend(frameon=False, fontsize=8)
    fig.suptitle("E5: a whale backing the wrong outcome — how far and how long the price is pushed off", fontsize=10)
    fig.tight_layout()
    path = out / "e5_deviation.png"
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return path
