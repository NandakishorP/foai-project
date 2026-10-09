"""Command line: `python -m tfs <command> ...`

  run CONFIG             run an experiment (all sweep points x seeds), write CSVs and charts
  plot-market CONFIG     plot one market of one seed: price vs p*_avail vs p*_full vs truth
  calibrate-costs CONFIG apply the research-cost calibration rule (DECISIONS D-017)
  calibrate-baseline CONFIG  choose rho and the cost median by the rule in DECISIONS D-026
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from tfs.core.config import load_config, load_raw
from tfs.experiments import plots
from tfs.experiments.runner import ExperimentResult, run_experiment
from tfs.simulation import run_season


def _charts(result: ExperimentResult, config_path: Path) -> list[Path]:
    """Draw the charts that fit the experiment's shape."""
    sweep = load_raw(config_path).get("sweep") or {}
    crossed = list(sweep.get("crossed") or {})
    ofat = list(sweep.get("one_at_a_time") or {})
    written = []
    if ofat and len(crossed) <= 1:
        group_by = crossed[0] if crossed else "point"
        written.append(plots.plot_ofat(result.summary, ofat, group_by, f"{result.name}: one factor at a time",
                                       result.out_dir / f"{result.name}_sweeps.png"))
    if result.points[0].config.season.n_markets > 1:
        for point in result.points:
            rows = [r for r in result.per_market if r["point"] == point.label]
            slug = point.label.replace("|", "__").replace("=", "-").replace(".", "_")
            written.append(plots.plot_season(rows, f"{result.name} ({point.label}): research participation over a season",
                                             result.out_dir / f"season_{slug}.png"))
    return written


def cmd_run(args: argparse.Namespace) -> None:
    result = run_experiment(args.config, out_root=args.out, workers=args.workers, n_seeds=args.seeds)
    print(f"wrote {result.out_dir}")
    for path in _charts(result, args.config):
        print(f"wrote {path}")


def cmd_plot_market(args: argparse.Namespace) -> None:
    cfg = load_config(args.config)
    season = run_season(cfg, args.seed)
    record = season.markets[args.market]
    path = args.out or Path("results") / cfg.name / f"market_seed{args.seed}_m{args.market}.png"
    title = f"{cfg.name}: seed {args.seed}, market {args.market} ({cfg.agents.belief_model})"
    print(f"wrote {plots.plot_market(record, title, path)}")


def cmd_calibrate_costs(args: argparse.Namespace) -> None:
    """Median gross profit of a researching forecaster (DECISIONS D-017)."""
    result = run_experiment(args.config, out_root=args.out, workers=args.workers, n_seeds=args.seeds)
    if len(result.points) != 1:
        raise SystemExit("calibration config must not have a sweep")
    pnls = np.array([p for run in result.results[0] for p in run.forecaster_gross_pnl])
    summary = {
        "rule": "DECISIONS D-017: cost_median = median gross trading profit of a researching forecaster",
        "cost_median": float(np.median(pnls)),
        "mean": float(pnls.mean()),
        "quartiles": [float(q) for q in np.percentile(pnls, [25, 75])],
        "n_values": int(pnls.size),
        "share_positive": float((pnls > 0).mean()),
    }
    (result.out_dir / "calibration.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


def cmd_calibrate_baseline(args: argparse.Namespace) -> None:
    from tfs.experiments.baseline_calibration import calibrate

    cfg = load_config(args.config)
    count = args.seeds if args.seeds is not None else cfg.seeds.count
    seeds = list(range(cfg.seeds.start, cfg.seeds.start + count))
    summary = calibrate(cfg, seeds, args.workers, args.out / "baseline_calibration")
    print(json.dumps(summary, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m tfs")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("config", type=Path)
        p.add_argument("--out", type=Path, default=Path("results"))
        p.add_argument("--workers", type=int, default=None, help="worker processes (default: all cores)")
        p.add_argument("--seeds", type=int, default=None, help="override the number of seeds")

    common(run := sub.add_parser("run", help="run an experiment"))
    run.set_defaults(func=cmd_run)
    common(cal := sub.add_parser("calibrate-costs", help="research-cost calibration (D-017)"))
    cal.set_defaults(func=cmd_calibrate_costs)

    common(cb := sub.add_parser("calibrate-baseline", help="baseline rho and cost calibration (D-026)"))
    cb.set_defaults(func=cmd_calibrate_baseline)

    pm = sub.add_parser("plot-market", help="plot one market of one seed")
    pm.add_argument("config", type=Path)
    pm.add_argument("--seed", type=int, default=0)
    pm.add_argument("--market", type=int, default=0)
    pm.add_argument("--out", type=Path, default=None)
    pm.set_defaults(func=cmd_plot_market)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
