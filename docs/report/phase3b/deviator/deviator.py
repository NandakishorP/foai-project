"""E4-V single deviator, individual readout (descriptive; computed after the E4 runs; changes no verdict).

The runs.csv of E4-V records only the researchers' *total* PnL. This asks the individual question:
does forecaster 0 earn more when it alone searches (the other nine use the capped rule) than when
it uses the capped rule like everyone else? Same seeds (paired), 1 reference predator, markets 6-30.

Run: .venv/bin/python docs/report/phase3b/deviator/deviator.py
"""
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from tfs.core.config import expand_sweep, load_raw, replace_in
from tfs.metrics.paired import mean_difference
from tfs.simulation import run_season

E4 = {p.label: p.config for p in expand_sweep(load_raw(Path("sim/experiments/configs/e4.yaml")))}
CAPPED = E4["agents.forecasters.execution.rule=capped|agents.predators.count=1|baseline"]
DEVIATOR = replace_in(E4["agents.forecasters.execution.rule=expectiminimax|agents.predators.count=1|baseline"],
                      "agents.forecasters.execution.users", 1)
SEEDS = range(100)


def own_and_others(task):
    cfg, seed = task
    markets = run_season(cfg, seed).markets[5:]
    own = np.mean([m.forecaster_pnl()[0] for m in markets])
    others = np.mean([np.mean([v for i, v in m.forecaster_pnl().items() if i != 0]) for m in markets])
    return own, others


if __name__ == "__main__":
    with ProcessPoolExecutor() as pool:
        capped = np.array(list(pool.map(own_and_others, [(CAPPED, s) for s in SEEDS])))
        deviator = np.array(list(pool.map(own_and_others, [(DEVIATOR, s) for s in SEEDS])))
    gain = mean_difference(deviator[:, 0], capped[:, 0])
    print(f"forecaster 0 PnL per market: capped like everyone {capped[:, 0].mean():.3f}, "
          f"lone searcher {deviator[:, 0].mean():.3f}; paired difference {gain.point:+.3f} [{gain.lo:+.3f}, {gain.hi:+.3f}]")
    print(f"the other nine (capped) per forecaster: {capped[:, 1].mean():.3f} -> {deviator[:, 1].mean():.3f}")
    print(f"{len(SEEDS)} seeds, markets 6-30, one reference predator")
