"""X-5 (EXPLORATORY; D-057): a crowd-aware order-splitting search vs TWAP and capped. Changes no verdict.

Reads results/x5/runs.csv (every forecaster uses the crowd-aware search; plus a single-deviator
variant) and results/e4/runs.csv (capped, twap, expectiminimax on the same seeds), markets 6-30.
Reports researcher PnL per researcher-market with and without the predator, the ratio to TWAP
(paired, joint bootstrap), leakage, reverts and truth lost. Then the single deviator's own PnL
(re-run here: runs.csv keeps only totals).

Run: .venv/bin/python docs/report/exploratory/x5/analysis.py
"""
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from tfs.core.config import expand_sweep, load_raw, replace_in
from tfs.experiments.h3 import joint, load_cells
from tfs.metrics.paired import mean_difference
from tfs.simulation import run_season

COLS = {"pnl_forecaster": "sum", "pnl_per_researcher": "mean", "forecaster_revert_share": "mean",
        "truth_mse": "mean", "pnl_predator": "mean"}


def e4_label(rule: str, k: int) -> str:
    return f"agents.forecasters.execution.rule={rule}|agents.predators.count={k}|baseline"


def ci(iv) -> str:
    return f"{iv.point:.3f} [{iv.lo:.3f}, {iv.hi:.3f}]"


def own_pnl(task):
    cfg, seed = task
    return float(np.mean([m.forecaster_pnl()[0] for m in run_season(cfg, seed).markets[5:]]))


if __name__ == "__main__":
    e4 = load_cells(Path("results/e4/runs.csv"), 5, COLS)
    x5 = load_cells(Path("results/x5/runs.csv"), 5, COLS)
    cells = {rule: (e4[e4_label(rule, 0)], e4[e4_label(rule, 1)]) for rule in ("capped", "twap", "expectiminimax")}
    e4v = load_cells(Path("results/e4_v/runs.csv"), 5, COLS)
    d2 = "agents.forecasters.execution.depth=2"
    cells["search, depth 2"] = (e4v[f"agents.predators.count=0|{d2}"], e4v[f"agents.predators.count=1|{d2}"])
    cells["crowd search d2"] = (x5["agents.predators.count=0|baseline"], x5["agents.predators.count=1|baseline"])
    d1 = "agents.forecasters.execution.depth=1"
    cells["crowd search d1"] = (x5[f"agents.predators.count=0|{d1}"], x5[f"agents.predators.count=1|{d1}"])
    n = len(cells["capped"][0]["pnl_forecaster"])
    twap1 = cells["twap"][1]["pnl_per_researcher"]
    twap0 = cells["twap"][0]["pnl_per_researcher"]
    print(f"{'rule':16s} {'P (0 pred)':>10s} {'P (1 pred)':>10s} {'P/TWAP, 1 pred':>24s} {'P/TWAP, 0 pred':>24s} "
          f"{'leakage':>24s} {'reverts':>8s} {'truth MSE':>10s}")
    for rule, (c0, c1) in cells.items():
        p0, p1 = c0["pnl_per_researcher"], c1["pnl_per_researcher"]
        r1 = joint(lambda idx: p1[idx].mean(1) / twap1[idx].mean(1), n)
        r0 = joint(lambda idx: p0[idx].mean(1) / twap0[idx].mean(1), n)
        a, b = c0["pnl_forecaster"], c1["pnl_forecaster"]
        leak = joint(lambda idx: 1 - b[idx].sum(1) / a[idx].sum(1), n)
        print(f"{rule:16s} {p0.mean():10.3f} {p1.mean():10.3f} {ci(r1):>24s} {ci(r0):>24s} {ci(leak):>24s} "
              f"{c1['forecaster_revert_share'].mean():8.3f} {c0['truth_mse'].mean():10.5f}")

    points = {p.label: p.config for p in expand_sweep(load_raw(Path("sim/experiments/configs/e4.yaml")))}
    capped = points[e4_label("capped", 1)]
    x5_cfg = {p.label: p.config for p in expand_sweep(load_raw(Path("sim/experiments/configs/x5.yaml")))}
    deviator = x5_cfg["agents.predators.count=1|agents.forecasters.execution.users=1"]
    seeds = range(100)
    with ProcessPoolExecutor() as pool:
        base = np.array(list(pool.map(own_pnl, [(capped, s) for s in seeds])))
        dev = np.array(list(pool.map(own_pnl, [(deviator, s) for s in seeds])))
    gain = mean_difference(dev, base)
    print(f"\nsingle deviator (1 predator, {len(seeds)} seeds): forecaster 0 earns {base.mean():.3f} with the capped "
          f"rule, {dev.mean():.3f} as the lone crowd-aware searcher; difference {gain.point:+.3f} "
          f"[{gain.lo:+.3f}, {gain.hi:+.3f}]")
