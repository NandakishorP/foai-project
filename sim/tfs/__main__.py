"""Command line: `python -m tfs <command> ...`

  run CONFIG             run an experiment (all sweep points x seeds), write CSVs and charts
  plot-market CONFIG     plot one market of one seed: price vs p*_avail vs p*_full vs truth
  calibrate-costs CONFIG apply the research-cost calibration rule (DECISIONS D-017)
  calibrate-baseline CONFIG  choose rho and the cost median by the rule in DECISIONS D-026
  replay CONFIG          explain, block by block, a front-run in one market of one seed
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
        group_by = crossed[0] if crossed else None
        written.append(plots.plot_ofat(result.summary, ofat, group_by, f"{result.name}: one factor at a time",
                                       result.out_dir / f"{result.name}_sweeps.png"))
    if "agents.predators.count" in crossed and result.points[0].config.season.n_markets > 1:
        written.append(plots.plot_season_compare(result.per_market, "agents.predators.count",
                                                 f"{result.name}: seasons with and without predators",
                                                 result.out_dir / f"{result.name}_seasons.png"))
    elif result.points[0].config.season.n_markets > 1:
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
    if result.verdict is not None:
        print(json.dumps(result.verdict, indent=2))


def _parse(value: str) -> object:
    """A CSV cell back to its Python value (numbers, None, booleans, otherwise text)."""
    if value in ("None", ""):
        return None
    if value in ("True", "False"):
        return value == "True"
    for kind in (int, float):
        try:
            return kind(value)
        except ValueError:
            pass
    return value


def cmd_charts(args: argparse.Namespace) -> None:
    """Redraw an experiment's charts from its saved summary.csv and per_market.csv (no rerun)."""
    import csv

    from tfs.core.config import expand_sweep

    raw = load_raw(args.config)
    out_dir = args.out / raw["name"]

    def rows(name: str) -> list[dict]:
        with (out_dir / name).open() as fh:
            return [{k: _parse(v) for k, v in r.items()} for r in csv.DictReader(fh)]

    result = ExperimentResult(raw["name"], out_dir, expand_sweep(raw), rows("summary.csv"), rows("per_market.csv"), [])
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


def cmd_replay(args: argparse.Namespace) -> None:
    from tfs.core.config import replace_in
    from tfs.experiments.replay import replay

    cfg = load_config(args.config)
    if args.predators is not None:
        cfg = replace_in(cfg, "agents.predators.count", args.predators)
    if args.engine == "evm":
        from tfs.experiments.replay import replay_on_chain

        path = replay_on_chain(cfg, args.seed, args.market, args.out / cfg.name)
        print(path.read_text())
        print(f"wrote {path}")
        return
    text, png = replay(cfg, args.seed, args.market, args.out / cfg.name)
    print(text.read_text())
    print(f"wrote {text}\nwrote {png}")


def cmd_h3(args: argparse.Namespace) -> None:
    from tfs.experiments.h3 import run

    summary = run(args.out / "e3_f", args.out / "e3_k", args.out / "e3_e", args.out / "e3")
    for name in ("H3a", "H3b", "H3c", "H3_overall"):
        print(f"{name}: {summary[name]['verdict']}")
    print(f"wrote {args.out / 'e3' / 'h3_verdicts.json'}")


def cmd_h4(args: argparse.Namespace) -> None:
    from tfs.experiments.h4 import run

    summary = run(args.out / "e4")
    print(f"H4: {summary['H4']['verdict']}")
    print(f"wrote {args.out / 'e4' / 'h4_verdict.json'}")


def cmd_search_bench(args: argparse.Namespace) -> None:
    """E4-search: nodes and time per decision, plain vs each pruning technique (descriptive)."""
    from tfs.core.config import expand_sweep
    from tfs.experiments.search_bench import benchmark, plot, sample_states, write

    points = {p.label: p.config for p in expand_sweep(load_raw(Path("sim/experiments/configs/e4.yaml")))}
    cfg = points["agents.forecasters.execution.rule=expectiminimax|agents.predators.count=1|baseline"]
    states = sample_states(cfg, range(3), args.states)
    rows = benchmark(cfg, states, plain_depth5_states=args.plain_depth5)
    out = args.out / "e4_search"
    print(f"{len(states)} states; wrote {write(rows, out)} and {plot(rows, out)}")
    for r in rows:
        print(f"{r.variant:22s} depth {r.depth}: {r.mean_nodes:10.1f} nodes, {r.mean_ms:8.2f} ms, "
              f"max |value - plain| {r.max_value_error:.1e}  ({r.states} states)")


def cmd_shock_study(args: argparse.Namespace) -> None:
    """Shock scenarios S-T, S-F, S-D, S-K (descriptive stability analysis, D-053)."""
    from tfs.experiments.runner import _git_state
    from tfs.experiments.shock_study import run

    out = run(args.config, args.seeds, args.workers, args.out, _git_state())
    print(f"wrote {out}")


def cmd_measure_env(args: argparse.Namespace) -> None:
    """Environment numbers for the order-splitting game, measured on baseline runs (D-053)."""
    from tfs.core.config import expand_sweep
    from tfs.experiments.environment import as_dict, measure_kappa, measure_predator

    def point(config: Path, label: str):
        return {p.label: p.config for p in expand_sweep(load_raw(config))}[label]

    no_predator = point(Path("sim/experiments/configs/e3_f.yaml"),
                        "mempool.policy=public|agents.predators.count=0|baseline")
    reference = point(Path("sim/experiments/configs/e2a.yaml"), "agents.predators.count=1|baseline")
    seeds = range(args.seeds)
    result = as_dict(measure_kappa(no_predator, seeds, first_market=5),
                     measure_predator(reference, seeds, first_market=5))
    out = args.out / "environment"
    out.mkdir(parents=True, exist_ok=True)
    (out / "environment.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


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

    ch = sub.add_parser("charts", help="redraw an experiment's charts from its saved CSVs")
    ch.add_argument("config", type=Path)
    ch.add_argument("--out", type=Path, default=Path("results"))
    ch.set_defaults(func=cmd_charts)

    pm = sub.add_parser("plot-market", help="plot one market of one seed")
    pm.add_argument("config", type=Path)
    pm.add_argument("--seed", type=int, default=0)
    pm.add_argument("--market", type=int, default=0)
    pm.add_argument("--out", type=Path, default=None)
    pm.set_defaults(func=cmd_plot_market)

    h3p = sub.add_parser("h3", help="pre-registered H3 verdicts from the E3-F, E3-K and E3-E runs")
    h3p.add_argument("--out", type=Path, default=Path("results"))
    h3p.set_defaults(func=cmd_h3)

    h4p = sub.add_parser("h4", help="pre-registered H4 verdict from the E4 runs")
    h4p.add_argument("--out", type=Path, default=Path("results"))
    h4p.set_defaults(func=cmd_h4)

    sb = sub.add_parser("search-bench", help="E4-search: pruning benchmark on sampled game states")
    sb.add_argument("--states", type=int, default=500)
    sb.add_argument("--plain-depth5", type=int, default=50, help="states for plain expectiminimax at depth 5")
    sb.add_argument("--out", type=Path, default=Path("results"))
    sb.set_defaults(func=cmd_search_bench)

    common(ss := sub.add_parser("shock-study", help="shock scenario: stability metrics and event-study plots"))
    ss.set_defaults(func=cmd_shock_study)

    me = sub.add_parser("measure-env", help="environment numbers for the order-splitting game (D-053)")
    me.add_argument("--seeds", type=int, default=50)
    me.add_argument("--out", type=Path, default=Path("results"))
    me.set_defaults(func=cmd_measure_env)

    rp = sub.add_parser("replay", help="explain a front-run block by block")
    rp.add_argument("config", type=Path)
    rp.add_argument("--seed", type=int, default=1)
    rp.add_argument("--market", type=int, default=10, help="0-based market index in the season")
    rp.add_argument("--predators", type=int, default=1, help="override the number of predators")
    rp.add_argument("--out", type=Path, default=Path("results"))
    rp.add_argument("--engine", choices=["fast", "evm"], default="fast",
                    help="evm: reproduce the block on the Solidity contracts (Anvil)")
    rp.set_defaults(func=cmd_replay)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
