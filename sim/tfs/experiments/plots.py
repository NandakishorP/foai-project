"""Static milestone and experiment charts (matplotlib, PNG).

Colours come from a validated categorical palette, assigned in fixed order. The
chrome is recessive: hairline grid, muted axes, text in ink colours, never in
series colours. Charts with two or more series get a legend and, where few
enough, direct labels.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")  # file output only; no display needed
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from tfs.simulation import MarketRecord  # noqa: E402

SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]  # categorical slots 1-4 (blue, orange, aqua, yellow)
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
BASELINE = "#c3c2b7"
LINE_WIDTH = 1.6


def _style(ax: plt.Axes) -> None:
    ax.set_facecolor(SURFACE)
    ax.grid(True, color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(BASELINE)
    ax.tick_params(colors=MUTED, labelcolor=INK_SECONDARY, labelsize=8)
    ax.xaxis.label.set_color(INK_SECONDARY)
    ax.yaxis.label.set_color(INK_SECONDARY)
    ax.title.set_color(INK)


def _figure(nrows: int, ncols: int, size: tuple[float, float], **kw: Any) -> tuple[plt.Figure, np.ndarray]:
    fig, axes = plt.subplots(nrows, ncols, figsize=size, squeeze=False, **kw)
    fig.patch.set_facecolor(SURFACE)
    for ax in axes.flat:
        _style(ax)
    return fig, axes


def _direct_label(ax: plt.Axes, x: float, y: float, text: str) -> None:
    ax.annotate(text, (x, y), xytext=(4, 0), textcoords="offset points", va="center", fontsize=8, color=INK_SECONDARY)


# --------------------------------------------------------------------------- #
# Milestone 1: one market, price vs the ideal prices vs the truth
# --------------------------------------------------------------------------- #


def plot_market(record: MarketRecord, title: str, path: Path) -> Path:
    ticks = np.arange(len(record.price_main))
    fig, axes = _figure(1, 1, (9.0, 4.6))
    ax = axes[0, 0]

    for k, shock in enumerate(record.shock_ticks):
        ax.axvline(shock, color=MUTED, linewidth=0.8, linestyle=":")
        ax.annotate("shock" if k == 0 else "", (shock, 1.0), xytext=(3, -10), textcoords="offset points",
                    fontsize=8, color=MUTED)
    ax.axhline(record.y, color=INK_SECONDARY, linewidth=1.0, linestyle="--")
    ax.annotate(f"truth: Y={record.y}", (ticks[-1], record.y), xytext=(-60, 6 if record.y == 0 else -12),
                textcoords="offset points", fontsize=8, color=INK_SECONDARY)

    # p*_full first, p*_avail dashed on top: at full participation they coincide and both stay visible.
    ax.plot(ticks, record.price_ref, color=MUTED, linewidth=1.0, label="reference venue price")
    ax.plot(ticks, record.p_full, color=SERIES[2], linewidth=LINE_WIDTH + 0.8, label="p*_full (all potential info)")
    ax.plot(ticks, record.p_avail, color=SERIES[1], linewidth=LINE_WIDTH, linestyle=(0, (4, 2)),
            label="p*_avail (acquired info)")
    ax.plot(ticks, record.price_main, color=SERIES[0], linewidth=LINE_WIDTH, label="market price (main)")

    ax.set_ylim(-0.02, 1.02)
    ax.set_xlim(0, ticks[-1])
    ax.set_xlabel("tick (block)")
    ax.set_ylabel("P(YES)")
    ax.set_title(title, loc="left", fontsize=11)
    handles, labels = ax.get_legend_handles_labels()
    legend = ax.legend(handles[::-1], labels[::-1], loc="upper center", bbox_to_anchor=(0.5, -0.14),
                       fontsize=8, frameon=False, ncols=4)
    for text in legend.get_texts():
        text.set_color(INK_SECONDARY)
    return _save(fig, path)


# --------------------------------------------------------------------------- #
# Milestone 2: participation over a season (and where truth was lost)
# --------------------------------------------------------------------------- #


def plot_season(per_market: Sequence[dict[str, Any]], title: str, path: Path) -> Path:
    markets = np.array([r["market"] for r in per_market]) + 1
    part = np.array([r["participation"] for r in per_market])
    lo = np.array([r["participation_lo"] for r in per_market])
    hi = np.array([r["participation_hi"] for r in per_market])
    agg = np.array([r["aggregation_mse"] for r in per_market])
    pmse = np.array([r["participation_mse"] for r in per_market])

    fig, axes = _figure(2, 1, (9.0, 6.4), sharex=True, gridspec_kw={"height_ratios": [3, 2]})
    top, bottom = axes[0, 0], axes[1, 0]

    top.fill_between(markets, lo * 100, hi * 100, color=SERIES[0], alpha=0.18, linewidth=0)
    top.plot(markets, part * 100, color=SERIES[0], linewidth=LINE_WIDTH, marker="o", markersize=4)
    top.set_ylim(0, 105)
    top.set_ylabel("forecasters researching (%)")
    top.set_title(title, loc="left", fontsize=11)
    _direct_label(top, markets[-1], part[-1] * 100, f"{part[-1] * 100:.0f}%")
    top.annotate("band: 95% CI across seeds", (0.01, 0.04), xycoords="axes fraction", fontsize=8, color=MUTED)

    bottom.stackplot(markets, agg, pmse, colors=[SERIES[0], SERIES[1]], alpha=0.85,
                     labels=["aggregation loss", "participation loss"], edgecolor=SURFACE, linewidth=1.0)
    bottom.set_ylabel("MSE vs p*_full")
    bottom.set_xlabel("market in season")
    legend = bottom.legend(loc="upper right", fontsize=8, frameon=False)
    for text in legend.get_texts():
        text.set_color(INK_SECONDARY)
    return _save(fig, path)


# --------------------------------------------------------------------------- #
# E1: one-factor-at-a-time sweeps, both belief models, 95% CIs
# --------------------------------------------------------------------------- #

E1_METRICS = [
    ("truth_rms", "truth lost (RMS)"),
    ("brier_final", "Brier score at close"),
    ("settled_0", "runs settling within ε of p*_avail\nafter the shock (share)"),
]


def plot_ofat(
    summary: Sequence[dict[str, Any]],
    swept: Sequence[str],
    group_by: str,
    title: str,
    path: Path,
    metrics: Sequence[tuple[str, str]] = E1_METRICS,
) -> Path:
    """Small multiples: one column per swept parameter, one row per metric, one line per `group_by` value.

    For each column, only the points where the other one-at-a-time parameters
    are at baseline are used, i.e. the baseline point plus that parameter's
    own variations.
    """
    groups = list(dict.fromkeys(row[group_by] for row in summary))
    fig, axes = _figure(len(metrics), len(swept), (3.3 * len(swept), 2.5 * len(metrics)))
    baseline = {row[group_by]: row for row in summary if row["point"].endswith("baseline")}

    for c, param in enumerate(swept):
        for r, (metric, label) in enumerate(metrics):
            ax = axes[r, c]
            for g_index, group in enumerate(groups):
                rows = [row for row in summary if row[group_by] == group and _varies_only(row, param, baseline[group], swept)]
                rows.sort(key=lambda row: row[param])
                xs = np.arange(len(rows)) + (g_index - (len(groups) - 1) / 2) * 0.08
                ys = np.array([row[metric] for row in rows], dtype=float)
                err = np.array([[y - row[f"{metric}_lo"], row[f"{metric}_hi"] - y] for y, row in zip(ys, rows)]).T
                ax.errorbar(xs, ys, yerr=err, color=SERIES[g_index], linewidth=LINE_WIDTH, marker="o",
                            markersize=5, capsize=2, label=str(group))
                ax.set_xticks(np.arange(len(rows)), [_fmt(row[param]) for row in rows])
            if r == 0:
                ax.set_title(param.split(".")[-1] if param != "agents.forecasters.count" else "informed forecasters",
                             fontsize=9, loc="left")
            if c == 0:
                ax.set_ylabel(label, fontsize=8)
    handles, labels = axes[0, 0].get_legend_handles_labels()
    legend = fig.legend(handles, labels, loc="upper right", ncols=len(groups), frameon=False, fontsize=8,
                        title=group_by.split(".")[-1], title_fontsize=8)
    for text in legend.get_texts():
        text.set_color(INK_SECONDARY)
    fig.suptitle(title, x=0.01, ha="left", fontsize=11, color=INK)
    fig.text(0.01, 0.005, "error bars: 95% CI across seeds", fontsize=7, color=MUTED)
    return _save(fig, path)


def _varies_only(row: dict[str, Any], param: str, baseline: dict[str, Any], swept: Sequence[str]) -> bool:
    return all(row[p] == baseline[p] for p in swept if p != param)


def _fmt(value: Any) -> str:
    if isinstance(value, float) and math.isfinite(value) and value == int(value):
        return str(int(value))
    return str(value)


def _save(fig: plt.Figure, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)
    return path
