"""Diagnosis of the E3 accuracy result (descriptive, run AFTER the verdicts; never alters them).

Shows that under sealed batches the main-market price cycles around the researchers' shared belief
instead of settling on it. Uniform clearing at the LMSR's *average* price (D-046) lets the
*marginal* price end beyond every filled limit; identical researcher orders (rho = 1) and the
one-tick proving delay then push it back and forth.

Run: .venv/bin/python docs/report/phase3a/diagnosis/oscillation.py
"""
from pathlib import Path

import numpy as np

from tfs.core.config import expand_sweep, load_raw, replace_in
from tfs.simulation import run_season

POINTS = {p.label: p.config for p in expand_sweep(load_raw(Path("sim/experiments/configs/e3_f.yaml")))}
PUB = replace_in(POINTS["mempool.policy=public|agents.predators.count=0|baseline"], "season.n_markets", 11)
ZK = replace_in(POINTS["mempool.policy=zk_batch|agents.predators.count=0|baseline"], "season.n_markets", 11)
VARIANTS = {
    "public": PUB,
    "private_relay": replace_in(PUB, "mempool.policy", "private_relay"),
    "zk_batch K=1": replace_in(ZK, "mempool.batch_interval", 1),
    "zk_batch K=5": ZK,
}


def tracking_error(cfg, seeds=range(20), market=10) -> float:
    """Mean |main price - p*_full| over the ticks of one market, averaged over seeds."""
    errs = []
    for seed in seeds:
        m = run_season(cfg, seed=seed).markets[market]
        errs.append(np.abs(m.price_main - m.p_full).mean())
    return float(np.mean(errs))


def batch_trace(cfg, seed=3, market=7, ticks=range(20, 36)) -> None:
    """Print the main price after each tick, then each batch's revealed orders (by agent kind, side, limit)."""
    log: list = []
    m = run_season(replace_in(cfg, "season.n_markets", market + 1), seed=seed,
                   trace_market=market, trace=[], batch_log=log).markets[market]
    for t in ticks:
        print(f"tick {t:2d}  p_full {m.p_full[t]:.3f}  main {m.price_main[t]:.3f}")
    for i in ticks:  # the log holds (revealed, unrevealed) per clearing, in order
        orders: dict = {}
        for o, _escrow in log[i][0]:
            key = (o.agent_id.split("_")[0], o.side.value, round(o.limit, 3))
            orders[key] = orders.get(key, 0.0) + o.size
        print(f"clearing {i:2d}: " + ", ".join(f"{k[0]} {k[1]}<={k[2]}: {v:.0f}" for k, v in orders.items()))


if __name__ == "__main__":
    print("Mean |main price - p*_full|, market 11, seeds 0-19, research forced, 0 predators:")
    for name, cfg in VARIANTS.items():
        print(f"  {name:14s} {tracking_error(cfg):.3f}")
    print("\nOne market (seed 3, market 8), zk_batch K=1. Sealed buys of NO are shown as their NO limit.")
    batch_trace(VARIANTS["zk_batch K=1"])
