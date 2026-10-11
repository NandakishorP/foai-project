"""Matplotlib figures for the dashboard and its PNG fallbacks (the same function draws both).

Style and palette come from tfs.experiments.plots, so the dashboard matches the report.
"""

from __future__ import annotations

from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from tfs.experiments.plots import BASELINE, GRID, INK, INK_SECONDARY, MUTED, SERIES, SURFACE, _figure  # noqa: E402
from tfs.search.expectiminimax import Node  # noqa: E402
from tfs.search.tree import Explained  # noqa: E402

KIND_COLOUR = {"forecaster": SERIES[0], "predator": SERIES[1], "arb": SERIES[2], "public": SERIES[3]}


def _colour(kind: str) -> str:
    return KIND_COLOUR.get(kind, MUTED)


# --------------------------------------------------------------------------- view 1: front-run replay


def replay_figure(replay: dict[str, Any], tick: int) -> plt.Figure:
    """Top: the market's price against the ideal price, the block marked. Bottom: each trade in the block."""
    fig, axes = _figure(2, 1, (9.5, 6.2), gridspec_kw={"height_ratios": [2, 3]})
    top, bottom = axes[:, 0]
    ticks = np.arange(len(replay["price_main"]))
    top.plot(ticks, replay["p_avail"], color=INK_SECONDARY, lw=1.2, ls="--", label="ideal price p*_avail")
    top.plot(ticks, replay["price_main"], color=SERIES[0], lw=1.6, label="main market price")
    top.axvline(tick, color=SERIES[1], lw=1.2)
    top.set_ylabel("YES price")
    top.legend(frameon=False, fontsize=8, loc="best")
    top.set_title(f"The market (outcome Y = {replay['y']}); block {tick} marked", fontsize=10, loc="left")

    block = replay["blocks"][tick]
    trades = [e for e in block["executed"] if e["main"]]
    for i, e in enumerate(trades):
        colour = _colour(e["kind"])
        if e["ok"]:
            bottom.plot([i, i + 1], [e["before"], e["after"]], color=colour, lw=3, solid_capstyle="butt")
        else:
            bottom.plot(i + 0.5, e["before"], marker="x", color=colour, ms=9, mew=2)
        if e["role"]:
            bottom.annotate(e["role"].split(" (")[0], (i + 0.5, max(e["before"], e["after"])), fontsize=7,
                            color=INK, xytext=(0, 6), textcoords="offset points", ha="center")
    bottom.set_xticks(np.arange(len(trades)) + 0.5, [e["agent"].replace("_", " ") for e in trades], rotation=60,
                      fontsize=7, ha="right")
    bottom.set_ylabel("price around each trade")
    bottom.set_title("Execution order chosen by the builder (line = filled, x = reverted)", fontsize=10, loc="left")
    fig.tight_layout()
    return fig


# --------------------------------------------------------------------------- view 2: PUBLIC vs ZK


def policies_figure(policies: dict[str, Any]) -> plt.Figure:
    names = list(policies)
    fig, axes = _figure(2, len(names), (5.2 * len(names), 5.4), sharex=True,
                        gridspec_kw={"height_ratios": [3, 1]})
    for c, name in enumerate(names):
        d = policies[name]
        ticks = np.arange(len(d["price_main"]))
        ax = axes[0, c]
        ax.plot(ticks, d["p_full"], color=INK_SECONDARY, lw=1.2, ls="--", label="ideal price p*_full")
        ax.plot(ticks, d["price_main"], color=SERIES[0], lw=1.6, label="main market price")
        ax.set_title(f"{name}, this market: truth-lost RMS {np.sqrt(d['truth_mse']):.3f}; predator PnL "
                     f"{d['pnl'].get('predator', 0.0):+.1f}", fontsize=10, loc="left")
        ax.set_ylim(0, 1)
        ax.legend(frameon=False, fontsize=8, loc="best")
        vol = axes[1, c]
        vol.bar(ticks, d["researcher_volume"], color=SERIES[0], width=1.0)
        vol.set_xlabel("block")
        vol.set_ylabel("researcher\nshares filled", fontsize=8)
    fig.tight_layout()
    return fig


# --------------------------------------------------------------------------- view 3: the search tree

MARKERS = {Node.MAX: "^", Node.MIN: "v", Node.CHANCE: "o", Node.TERMINAL: "s"}


def _layout(nodes: list) -> dict[tuple, tuple[float, float]]:
    """Leaves evenly spaced left to right in search order; each parent centred over its children."""
    children: dict[tuple, list[tuple]] = {}
    for n in nodes:
        if n.path:
            children.setdefault(n.path[:-1], []).append(n.path)
    pos: dict[tuple, tuple[float, float]] = {}
    next_x = [0.0]

    def place(path: tuple) -> float:
        kids = children.get(path, [])
        x = float(np.mean([place(k) for k in kids])) if kids else next_x[0]
        if not kids:
            next_x[0] += 1.0
        pos[path] = (x, -len(path))
        return x

    place(())
    return pos


def _fmt(action: object) -> str:
    return f"{action:.1f}" if isinstance(action, float) else str(action)


def tree_figure(ex: Explained, title: str) -> plt.Figure:
    pos = _layout(ex.nodes)
    width = max(8.0, 0.16 * max(x for x, _ in pos.values()))
    fig, ax = plt.subplots(figsize=(min(max(width, 9.0), 22.0), 5.2), facecolor=SURFACE)
    ax.set_facecolor(SURFACE)
    status_colour = {"visited": SERIES[0], "tt": SERIES[2], "pruned": BASELINE}
    by_path = {n.path: n for n in ex.nodes}
    for n in ex.nodes:
        if n.path:
            (x0, y0), (x1, y1) = pos[n.path[:-1]], pos[n.path]
            ax.plot([x0, x1], [y0, y1], color=GRID if n.status == "pruned" else MUTED, lw=0.8, zorder=1)
    for n in ex.nodes:
        x, y = pos[n.path]
        marker = "s" if n.leaf else MARKERS[n.kind]
        ax.scatter(x, y, marker=marker, s=60 if len(ex.nodes) < 60 else 18, color=status_colour[n.status],
                   edgecolors=INK if n.status != "pruned" else "none", linewidths=0.4, zorder=2)
        if len(ex.nodes) <= 40 and n.status != "pruned":  # value seen from the parent: edge reward + value to come
            ax.annotate(f"{n.reward + n.value:.2f}", (x, y), fontsize=7, xytext=(0, -11),
                        textcoords="offset points", ha="center", color=INK)
    root = by_path[()]
    ax.set_title(f"{title}\nplain expectiminimax: {ex.plain.nodes} nodes · pruned search: {ex.pruned.nodes} nodes "
                 f"({ex.pruned.tt_hits} answered by the transposition table)\n"
                 f"best first move {_fmt(ex.best_action)} · value {root.value:.3f}", fontsize=9, loc="left")
    handles = [plt.Line2D([], [], marker=m, ls="", color=INK_SECONDARY, label=l) for m, l in
               (("^", "MAX (forecaster)"), ("v", "MIN (predator)"), ("o", "CHANCE"), ("s", "leaf / cut-off"))]
    handles += [plt.Line2D([], [], marker="o", ls="", color=c, label=l) for l, c in
                (("visited", SERIES[0]), ("table hit", SERIES[2]), ("pruned (never looked at)", BASELINE))]
    ax.legend(handles=handles, frameon=False, fontsize=7, ncol=7, loc="lower center", bbox_to_anchor=(0.5, -0.18))
    ax.set_axis_off()
    fig.tight_layout()
    return fig


# --------------------------------------------------------------------------- view 5: verdicts (fallback)


def verdicts_figure(rows: list[tuple[str, str, str]]) -> plt.Figure:
    fig, ax = plt.subplots(figsize=(11, 0.5 + 0.42 * len(rows)), facecolor=SURFACE)
    ax.set_axis_off()
    table = ax.table(cellText=[list(r) for r in rows], colLabels=["Hypothesis", "Measured", "Verdict"],
                     loc="center", cellLoc="left", colWidths=[0.28, 0.54, 0.18])
    table.auto_set_font_size(False)
    table.set_fontsize(8)
    table.scale(1, 1.4)
    fig.tight_layout()
    return fig
