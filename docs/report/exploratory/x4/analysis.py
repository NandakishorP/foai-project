"""X-4 (EXPLORATORY): marginal vs average batch clearing, paired on seeds with E3-F. Changes no verdict.

Reads results/x4/runs.csv (marginal clearing) and results/e3_f/runs.csv (average clearing, the
pre-registered E3 rule) and reports, for each policy and predator count, over markets 6-30:
truth-lost RMS, researchers' fill (unfilled share), researcher profit, the predator's take
(PnL and leakage), and the LMSR surplus that marginal clearing leaves with the market maker.

Run: .venv/bin/python docs/report/exploratory/x4/analysis.py
"""
from pathlib import Path

import numpy as np

from tfs.experiments.h3 import joint, load_cells

COLS = {"truth_mse": "mean", "forecaster_unfilled_share": "mean", "pnl_per_researcher": "mean",
        "pnl_forecaster": "sum", "pnl_predator": "mean", "lmsr_surplus": "mean"}
PUB0 = "mempool.policy=public|agents.predators.count=0|baseline"


def label(policy: str, k: int) -> str:
    return f"mempool.policy={policy}|agents.predators.count={k}|baseline"


def ci(iv) -> str:
    return f"{iv.point:+.3f} [{iv.lo:+.3f}, {iv.hi:+.3f}]"


x4 = load_cells(Path("results/x4/runs.csv"), 5, COLS)
e3 = load_cells(Path("results/e3_f/runs.csv"), 5, {k: v for k, v in COLS.items() if k != "lmsr_surplus"})
pub = x4[PUB0]["truth_mse"]
n = len(pub)
print("Truth-lost RMS relative to PUBLIC without predators (same seeds), and the predator's take")
print(f"{'cell':34s} {'RMS vs PUB0':>24s} {'unfilled':>9s} {'P/res':>7s} {'pred PnL':>9s} {'surplus/mkt':>11s}")
for policy in ("public", "commit_reveal", "zk_batch"):
    for k in (0, 1):
        c = x4[label(policy, k)]
        rms = joint(lambda idx, m=c["truth_mse"]: np.sqrt(m[idx].sum(1) / pub[idx].sum(1)) - 1, n)
        print(f"marginal {policy:13s} pred={k}        {ci(rms):>24s} {c['forecaster_unfilled_share'].mean():9.3f} "
              f"{c['pnl_per_researcher'].mean():7.3f} {c['pnl_predator'].mean():9.3f} {c['lmsr_surplus'].mean():11.3f}")
for k in (0, 1):
    c = e3[label("zk_batch", k)]
    rms = joint(lambda idx, m=c["truth_mse"]: np.sqrt(m[idx].sum(1) / pub[idx].sum(1)) - 1, n)
    print(f"average  zk_batch      pred={k} (E3-F) {ci(rms):>24s} {c['forecaster_unfilled_share'].mean():9.3f} "
          f"{c['pnl_per_researcher'].mean():7.3f} {c['pnl_predator'].mean():9.3f} {'0':>11s}")

print("\nLeakage (share of the researchers' edge lost to the predator, vs each cell's own 0-predator twin)")
for name, cells, policy in (("marginal", x4, "public"), ("marginal", x4, "commit_reveal"), ("marginal", x4, "zk_batch"),
                            ("average (E3-F)", e3, "zk_batch")):
    a, b = cells[label(policy, 0)]["pnl_forecaster"], cells[label(policy, 1)]["pnl_forecaster"]
    leak = joint(lambda idx: 1 - b[idx].sum(1) / a[idx].sum(1), n)
    print(f"  {name:15s} {policy:13s} L = {ci(leak)}")

print("\nZK accuracy, marginal vs average clearing (paired): RMS(marginal) / RMS(average) - 1")
for k in (0, 1):
    m, a = x4[label("zk_batch", k)]["truth_mse"], e3[label("zk_batch", k)]["truth_mse"]
    print(f"  pred={k}: {ci(joint(lambda idx: np.sqrt(m[idx].sum(1) / a[idx].sum(1)) - 1, n))}")
