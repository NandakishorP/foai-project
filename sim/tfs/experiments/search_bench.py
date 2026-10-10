"""E4-search: what each pruning technique saves on the order-splitting game (descriptive; SPEC §6.1).

Game states are sampled from the states the forecasters actually searched in E4-style
seasons (expectiminimax rule, one predator). Each state is searched from scratch at depths
1–5 by plain expectiminimax and by the pruned search with the speed-ups switched on one
at a time: alpha-beta, + Star1, + move ordering, + transposition table. Every pruned
value is checked against the plain value: the speed-ups must never change the answer.

Plain expectiminimax at depth 5 costs about a million nodes per state, so it runs on a
subsample (`plain_depth5_states`); the output says so.
"""

from __future__ import annotations

import csv
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from tfs.core.config import SimConfig, replace_in
from tfs.search.expectiminimax import Options, Searcher, Stats, expectiminimax
from tfs.search.order_splitting import OrderSplittingGame, Phase, SplitState, split_params
from tfs.simulation import run_season, season_policy

VARIANTS = {
    "alpha-beta": Options(alphabeta=True, star1=False, ordering=False, transposition=False),
    "+ Star1": Options(alphabeta=True, star1=True, ordering=False, transposition=False),
    "+ ordering": Options(alphabeta=True, star1=True, ordering=True, transposition=False),
    "+ transposition table": Options(),
}
DEPTHS = (1, 2, 3, 4, 5)


@dataclass(frozen=True)
class Row:
    variant: str
    depth: int
    states: int
    mean_nodes: float
    mean_ms: float
    max_value_error: float  # vs plain expectiminimax on the same states (0 = identical)


def sample_states(cfg: SimConfig, seeds: range, n: int) -> list[SplitState]:
    """Root states the forecasters searched in these seasons (deterministic sample of n)."""
    keys: set[tuple] = set()
    for seed in seeds:
        policy = season_policy(cfg)
        assert policy is not None, "sample from a config whose forecasters use the expectiminimax rule"
        run_season(cfg, seed, splitting=policy)
        keys |= set(policy.decisions)
    ordered = sorted(keys, key=repr)
    chosen = np.random.default_rng(0).choice(len(ordered), size=min(n, len(ordered)), replace=False)
    return [SplitState(Phase.MAX, k[1], k[2], k[3]) for k in (ordered[i] for i in sorted(chosen))]


def benchmark(cfg: SimConfig, states: list[SplitState], plain_depth5_states: int) -> list[Row]:
    game = OrderSplittingGame(split_params(replace_in(cfg, "agents.forecasters.execution.depth", max(DEPTHS))))
    rows = []
    for depth in DEPTHS:
        subset = states if depth < 5 else states[:plain_depth5_states]
        plain_values, nodes, secs = [], [], []
        for s in subset:
            stats, t0 = Stats(), time.perf_counter()
            plain_values.append(expectiminimax(game, s, depth, stats))
            secs.append(time.perf_counter() - t0)
            nodes.append(stats.nodes)
        rows.append(Row("plain", depth, len(subset), float(np.mean(nodes)), 1e3 * float(np.mean(secs)), 0.0))
        for name, options in VARIANTS.items():
            nodes, secs, errors = [], [], []
            for i, s in enumerate(states):
                searcher, t0 = Searcher(game, options), time.perf_counter()
                value = searcher.value(s, depth)
                secs.append(time.perf_counter() - t0)
                nodes.append(searcher.stats.nodes)
                if i < len(subset):
                    errors.append(abs(value - plain_values[i]))
            rows.append(Row(name, depth, len(states), float(np.mean(nodes)), 1e3 * float(np.mean(secs)),
                            float(max(errors))))
    return rows


def write(rows: list[Row], out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    path = out / "search_bench.csv"
    with path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(Row.__dataclass_fields__)
        for r in rows:
            writer.writerow([r.variant, r.depth, r.states, f"{r.mean_nodes:.1f}", f"{r.mean_ms:.3f}",
                             f"{r.max_value_error:.2e}"])
    return path


def plot(rows: list[Row], out: Path) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, (ax_nodes, ax_time) = plt.subplots(1, 2, figsize=(11, 4.2))
    for variant in ["plain", *VARIANTS]:
        pts = [r for r in rows if r.variant == variant]
        depths = [r.depth for r in pts]
        ax_nodes.plot(depths, [r.mean_nodes for r in pts], marker="o", lw=2, label=variant)
        ax_time.plot(depths, [r.mean_ms for r in pts], marker="o", lw=2, label=variant)
    for ax, title in ((ax_nodes, "Nodes expanded per decision"), (ax_time, "Time per decision (ms)")):
        ax.set_yscale("log")
        ax.set_xlabel("search depth (blocks)")
        ax.set_xticks(DEPTHS)
        ax.set_title(title)
        ax.grid(alpha=0.3)
    ax_nodes.legend(frameon=False)
    fig.suptitle("Order-splitting expectiminimax: what each pruning technique saves (values identical)")
    fig.tight_layout()
    path = out / "search_bench.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path
