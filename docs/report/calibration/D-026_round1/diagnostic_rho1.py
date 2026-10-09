import numpy as np
from tfs.core.config import load_config, replace_in, SweepPoint
from tfs.experiments.runner import run_points

def main():
    base = replace_in(load_config("sim/experiments/configs/base.yaml"), "information.private.rho", 1.0)
    variants = {
      "rho=1 base": [],
      "no arbitrageur": [("agents.arbitrageurs.count", 0)],
      "no ref-venue public trader": [("agents.public_ref.count", 0)],
      "forecaster bankroll x4": [("agents.forecasters.bankroll", 400.0)],
      "full Kelly (k=1)": [("agents.forecasters.kelly_fraction", 1.0)],
      "max_order x5": [("agents.forecasters.max_order", 100.0)],
      "b_main 30": [("market.b_main", 30.0)],
      "no noise traders (main)": [("agents.noise_main.count", 0)],
      "no trend followers": [("agents.trend.count", 0)],
      "forecaster public latency 0": [("agents.forecasters.public_latency", 0)],
    }
    pts = []
    for name, ch in variants.items():
        c = base
        for k, v in ch: c = replace_in(c, k, v)
        pts.append(SweepPoint(name, {}, c))
    for p, r in zip(pts, run_points(pts, list(range(150)), None)):
        rows = [row for run in r for row in run.rows]
        agg = np.mean([x["aggregation_mse"] for x in rows]); pub = np.mean([x["public_only_mse"] for x in rows])
        print(f"{p.label:30s} research_captured {1-agg/pub:6.2f}   aggregation RMS {np.sqrt(agg):.3f}   forecaster pnl/market {np.mean([x['pnl_forecaster'] for x in rows])/10:6.2f}")

if __name__ == "__main__":
    main()
