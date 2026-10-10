"""H3 verdicts exactly as pre-registered (docs/PREREGISTRATION.md, H3 section; DECISIONS D-046).

Inputs are the per-run CSVs of E3-F, E3-K and E3-E. Every experiment runs seeds 0..199, so
seed i in every cell shares its random draws. Statistics combining cells are therefore
bootstrapped *jointly*: one resample of seed indices is applied to every cell at once
(10,000 resamples, bootstrap seed 0). A threshold counts only if the whole 95% CI clears it.
The rule functions are short and literal, so they can be checked line by line against
PREREGISTRATION.md.
"""

from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np

from tfs.experiments.verdicts import CONTRADICTED, PARTLY, SUPPORTED
from tfs.metrics.paired import Interval, paired_bootstrap

K_GRID = (1, 2, 5, 10, 20)
F_FIRST, E_FIRST = 5, 20  # 0-based first scored market: 6-30 (E3-F/K), 21-30 (E3-E)

# --------------------------------------------------------------------------- #
# The rules (literal)
# --------------------------------------------------------------------------- #


def h3a_verdict(ratio: Interval) -> str:
    """R = L_ZK / L_PUB: supported if CI(R) <= 0.5; contradicted if CI(R) >= 0.9."""
    if ratio.hi <= 0.5:
        return SUPPORTED
    if ratio.lo >= 0.9:
        return CONTRADICTED
    return PARTLY


def h3b_verdict(profit_ratio: Interval, unfilled_gap_pp: Interval) -> str:
    """Supported if CI(P) >= 1.10 and CI(U_PUB - U_ZK) >= 10 pp; contradicted if CI(P) <= 1.00."""
    if profit_ratio.lo >= 1.10 and unfilled_gap_pp.lo >= 10.0:
        return SUPPORTED
    if profit_ratio.hi <= 1.00:
        return CONTRADICTED
    return PARTLY


def h3c_verdict(delta_t5: Interval, slope: Interval, k: int = 5) -> str:
    """Supported if CI(ΔT(5)) > 0, CI(ΔT(20) - ΔT(1)) > 0 and upper CI(ΔT(5)) <= 2K;
    contradicted if CI(ΔT(5)) <= 0 or CI(ΔT(5)) > 3K."""
    if delta_t5.lo > 0 and slope.lo > 0 and delta_t5.hi <= 2 * k:
        return SUPPORTED
    if delta_t5.hi <= 0 or delta_t5.lo > 3 * k:
        return CONTRADICTED
    return PARTLY


def h3_overall_verdict(h3a: str, h3c: str, rms_change: Interval, participation_gain_pp: Interval) -> str:
    """Supported if H3a supported, H3c not contradicted, CI(RMS change) < 0 and CI(participation gain) > 0;
    contradicted if H3a contradicted or CI(RMS change) >= 0."""
    if h3a == SUPPORTED and h3c != CONTRADICTED and rms_change.hi < 0 and participation_gain_pp.lo > 0:
        return SUPPORTED
    if h3a == CONTRADICTED or rms_change.lo >= 0:
        return CONTRADICTED
    return PARTLY


# --------------------------------------------------------------------------- #
# Per-seed data from runs.csv
# --------------------------------------------------------------------------- #

Cell = dict[str, np.ndarray]  # column -> per-seed value (seeds ascending)


def load_cells(runs_csv: Path, first_market: int, columns: dict[str, str]) -> dict[str, Cell]:
    """For every sweep point: per-seed mean (or sum, if columns[c] == 'sum') of each column over scored markets."""
    rows: dict[str, dict[int, list[dict[str, str]]]] = defaultdict(lambda: defaultdict(list))
    with Path(runs_csv).open() as fh:
        for r in csv.DictReader(fh):
            if int(float(r["market"])) >= first_market:
                rows[r["point"]][int(float(r["seed"]))].append(r)
    cells: dict[str, Cell] = {}
    for point, by_seed in rows.items():
        seeds = sorted(by_seed)
        cell: Cell = {}
        for column, how in columns.items():
            values = []
            for s in seeds:
                xs = np.array([float(r[column]) for r in by_seed[s]])
                values.append(np.nansum(xs) if how == "sum" else np.nanmean(xs))
            cell[column] = np.array(values)
        cells[point] = cell
    return cells


def joint(stat: Callable[[np.ndarray], np.ndarray], n: int) -> Interval:
    """Joint paired bootstrap: `stat` receives an (R, n) array of seed indices, applied to every cell alike."""
    return Interval(*paired_bootstrap(stat, n))


# --------------------------------------------------------------------------- #
# The statistics
# --------------------------------------------------------------------------- #

PUB0, PUB1 = "mempool.policy=public|agents.predators.count=0|baseline", "mempool.policy=public|agents.predators.count=1|baseline"
ZK0, ZK1 = "mempool.policy=zk_batch|agents.predators.count=0|baseline", "mempool.policy=zk_batch|agents.predators.count=1|baseline"


def k_label(predators: int, k: int) -> str:
    suffix = "baseline" if k == 5 else f"mempool.batch_interval={k}"
    return f"agents.predators.count={predators}|{suffix}"


def h3a_stats(f: dict[str, Cell]) -> dict[str, Interval]:
    inf = {c: f[c]["pnl_forecaster"] for c in (PUB0, PUB1, ZK0, ZK1)}
    n = len(inf[PUB0])

    def leak(c1: str, c0: str, idx: np.ndarray) -> np.ndarray:
        return 1.0 - inf[c1][idx].sum(1) / inf[c0][idx].sum(1)

    return {
        "L_PUB": joint(lambda idx: leak(PUB1, PUB0, idx), n),
        "L_ZK": joint(lambda idx: leak(ZK1, ZK0, idx), n),
        "R": joint(lambda idx: leak(ZK1, ZK0, idx) / leak(PUB1, PUB0, idx), n),
    }


def h3b_stats(f: dict[str, Cell]) -> dict[str, Interval]:
    p_pub, p_zk = f[PUB0]["pnl_per_researcher"], f[ZK0]["pnl_per_researcher"]
    u_pub, u_zk = f[PUB0]["forecaster_unfilled_share"], f[ZK0]["forecaster_unfilled_share"]
    n = len(p_pub)
    return {
        "P_ratio": joint(lambda idx: p_zk[idx].sum(1) / p_pub[idx].sum(1), n),
        "U_gap_pp": joint(lambda idx: 100.0 * (u_pub[idx].mean(1) - u_zk[idx].mean(1)), n),
        "U_PUB": joint(lambda idx: u_pub[idx].mean(1), n),
        "U_ZK": joint(lambda idx: u_zk[idx].mean(1), n),
    }


def h3c_stats(f: dict[str, Cell], k: dict[str, Cell], predators: int = 0) -> dict[str, Interval]:
    t_pub = f[PUB1 if predators else PUB0]["rmst_eps_0"]
    n = len(t_pub)
    out = {}
    for kk in K_GRID:
        t_zk = k[k_label(predators, kk)]["rmst_eps_0"]
        out[f"dT_{kk}"] = joint(lambda idx, t=t_zk: (t[idx] - t_pub[idx]).mean(1), n)
    t1, t20 = k[k_label(predators, 1)]["rmst_eps_0"], k[k_label(predators, 20)]["rmst_eps_0"]
    out["slope_20_minus_1"] = joint(lambda idx: (t20[idx] - t1[idx]).mean(1), n)
    return out


def overall_stats(e: dict[str, Cell]) -> dict[str, Interval]:
    mse_pub, mse_zk = e[PUB1]["truth_mse"], e[ZK1]["truth_mse"]
    part_pub, part_zk = e[PUB1]["participation"], e[ZK1]["participation"]
    n = len(mse_pub)
    return {
        "rms_change": joint(lambda idx: np.sqrt(mse_zk[idx].sum(1) / mse_pub[idx].sum(1)) - 1.0, n),
        "participation_gain_pp": joint(lambda idx: 100.0 * (part_zk[idx].mean(1) - part_pub[idx].mean(1)), n),
    }


def interaction(cells: dict[str, Cell], metric: str) -> dict[str, Interval]:
    """total = PUB1 - ZK1 = anti-crowding (PUB0 - ZK0) + anti-predator ((PUB1-PUB0) - (ZK1-ZK0)), exactly."""
    m = {c: cells[c][metric] for c in (PUB0, PUB1, ZK0, ZK1)}
    n = len(m[PUB0])

    def mean(c: str, idx: np.ndarray) -> np.ndarray:
        return m[c][idx].mean(1)

    def total(idx):
        return mean(PUB1, idx) - mean(ZK1, idx)

    def crowd(idx):
        return mean(PUB0, idx) - mean(ZK0, idx)

    def pred(idx):
        return (mean(PUB1, idx) - mean(PUB0, idx)) - (mean(ZK1, idx) - mean(ZK0, idx))

    return {
        "total": joint(total, n),
        "anti_crowding": joint(crowd, n),
        "anti_predator": joint(pred, n),
        "anti_crowding_share": joint(lambda idx: crowd(idx) / total(idx), n),
        "anti_predator_share": joint(lambda idx: pred(idx) / total(idx), n),
    }


COLUMNS_F = {"pnl_forecaster": "sum", "pnl_per_researcher": "mean", "forecaster_unfilled_share": "mean",
             "rmst_eps_0": "mean", "truth_mse": "mean", "participation": "mean", "fill_rate": "mean",
             "exec_delay": "mean", "pnl_predator": "mean"}


def run(f_dir: Path, k_dir: Path, e_dir: Path, out: Path) -> dict[str, Any]:
    f = load_cells(f_dir / "runs.csv", F_FIRST, COLUMNS_F)
    k = load_cells(k_dir / "runs.csv", F_FIRST, COLUMNS_F)
    e = load_cells(e_dir / "runs.csv", E_FIRST, COLUMNS_F)
    a, b = h3a_stats(f), h3b_stats(f)
    c0, c1 = h3c_stats(f, k, 0), h3c_stats(f, k, 1)
    o = overall_stats(e)
    va = h3a_verdict(a["R"])
    vb = h3b_verdict(b["P_ratio"], b["U_gap_pp"])
    vc = h3c_verdict(c0["dT_5"], c0["slope_20_minus_1"])
    vo = h3_overall_verdict(va, vc, o["rms_change"], o["participation_gain_pp"])

    def d(stats: dict[str, Interval]) -> dict[str, Any]:
        return {name: asdict(iv) for name, iv in stats.items()}

    summary = {
        "rule": "docs/PREREGISTRATION.md, H3 (joint paired bootstrap over seeds, 10,000 resamples, seed 0)",
        "H3a": {"verdict": va, **d(a)},
        "H3b": {"verdict": vb, **d(b)},
        "H3c": {"verdict": vc, "zero_predators": d(c0), "one_predator_reported_alongside": d(c1)},
        "H3_overall": {"verdict": vo, **d(o)},
        "interaction_E3E": {m: d(interaction(e, m)) for m in ("truth_mse", "participation", "pnl_per_researcher")},
        "interaction_E3F": {m: d(interaction(f, m)) for m in ("truth_mse", "pnl_per_researcher")},
        "costs_vs_K": {
            f"K={kk}|pred={p}": {col: float(np.mean(k[k_label(p, kk)][col])) for col in
                                 ("rmst_eps_0", "fill_rate", "exec_delay", "truth_mse", "pnl_per_researcher")}
            for kk in K_GRID for p in (0, 1)
        },
        "public_reference": {c: {col: float(np.mean(f[c][col])) for col in ("rmst_eps_0", "fill_rate", "truth_mse",
                                                                              "pnl_per_researcher")}
                             for c in (PUB0, PUB1)},
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "h3_verdicts.json").write_text(json.dumps(summary, indent=2, default=lambda x: None if math.isnan(x) else x))
    return summary
