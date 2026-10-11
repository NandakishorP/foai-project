"""Precomputed data for the review-day dashboard (DECISIONS D-062). Deterministic; run `tfs dashboard-data`.

The dashboard never runs long simulations. This module runs the two markets it replays, once,
and saves them as small JSON files in `dashboard/data/`:
- replay.json: the archived E2a front-run market (seed 3, market 16 = index 15), block by
  block: what was pending, what the predator could see and decided, how the builder ordered
  the block, and how each trade moved the price;
- policies.json: the same seed and market under PUBLIC and ZK_BATCH (E3-F, one predator).

Both markets were fixed in advance (the Phase 2a replay market), not picked for how they look.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from tfs.core.config import expand_sweep, load_raw
from tfs.core.types import Bundle, Trade, Venue
from tfs.simulation import BlockTrace, MarketRecord, run_season

SEED, MARKET = 3, 15  # the Phase 2a replay market (D-036): seed 3, market 16 counted from 1
E2A = (Path("sim/experiments/configs/e2a.yaml"), "agents.predators.count=1|baseline")
E3F = Path("sim/experiments/configs/e3_f.yaml")
POLICIES = {"PUBLIC": "mempool.policy=public|agents.predators.count=1|baseline",
            "ZK_BATCH": "mempool.policy=zk_batch|agents.predators.count=1|baseline"}


def _config(path: Path, label: str):
    return {p.label: p.config for p in expand_sweep(load_raw(path))}[label]


def _kind(agent_id: str) -> str:
    return agent_id.rsplit("_", 1)[0].split("_")[0]


def _text(trade: Trade) -> str:
    verb = "buy" if trade.shares > 0 else "sell"
    venue = "" if trade.venue is Venue.MAIN else " (reference venue)"
    bound = "at most" if trade.shares > 0 else "at least"  # a sell's limit is a minimum price
    return f"{verb} {abs(trade.shares):.1f} {trade.side.value.upper()} {bound} {trade.limit_price:.3f}{venue}"


def _block(block: BlockTrace) -> dict[str, Any]:
    roles: dict[int, str] = {}
    for request, victim in block.plan.placements:
        roles[id(request.front)] = f"front-run of #{victim.tx_id} (bid {request.bid:.3f})"
        roles[id(victim.tx)] = "victim"
    seen = set().union(*block.visible.values()) if block.visible else set()
    pending = [{"id": p.tx_id, "arrival": round(p.arrival, 3), "sender": p.sender, "kind": _kind(p.sender),
                "text": "arbitrage bundle" if isinstance(p.tx, Bundle) else _text(p.tx), "seen": p.tx_id in seen}
               for p in sorted(block.pending, key=lambda p: p.arrival)]
    flat = [t for tx in block.plan.txs for t in (tx.trades if isinstance(tx, Bundle) else (tx,))]
    executed = [{"agent": t.agent_id, "kind": _kind(t.agent_id), "text": _text(t), "before": r.price_before,
                 "after": r.price_after, "ok": r.ok, "reason": r.reason, "role": roles.get(id(t), ""),
                 "main": t.venue is Venue.MAIN} for t, r in zip(flat, block.receipts)]
    decisions = {}
    for pid, d in block.decisions.items():
        decisions[pid] = None if d is None else {
            "victim": d.victim.sender, "victim_id": d.victim.tx_id, "shares": d.shares, "p_informed": d.p_informed,
            "ev_gross": d.ev_gross, "bid": d.bid, "ev_net": d.ev_net}
    return {"tick": block.tick, "before": block.price_before, "after": block.price_after,
            "frontrun": bool(block.plan.placements), "pending": pending, "executed": executed, "decisions": decisions}


def _series(record: MarketRecord) -> dict[str, Any]:
    return {"y": record.y, "price_main": record.price_main.tolist(), "price_ref": record.price_ref.tolist(),
            "p_avail": record.p_avail.tolist(), "p_full": record.p_full.tolist(),
            "researcher_volume": record.volume_main.get("forecaster", np.zeros(len(record.price_main))).tolist(),
            "pnl": {kind: sum(v for a, v in record.pnl.items() if record.kinds[a] == kind)
                    for kind in sorted(set(record.kinds.values()))},
            "truth_mse": float(np.mean((record.price_main - record.p_full) ** 2))}


def build(out: Path, git_state: dict) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    trace: list[BlockTrace] = []
    record = run_season(_config(*E2A), SEED, trace_market=MARKET, trace=trace).markets[MARKET]
    replay = {"source": f"{E2A[0]} [{E2A[1]}], seed {SEED}, market {MARKET + 1}", **_series(record),
              "blocks": [_block(b) for b in trace]}
    policies = {}
    for name, label in POLICIES.items():
        policies[name] = {"source": f"{E3F} [{label}], seed {SEED}, market {MARKET + 1}",
                          **_series(run_season(_config(E3F, label), SEED).markets[MARKET])}
    written = []
    for name, payload in (("replay.json", replay), ("policies.json", {"policies": policies})):
        path = out / name
        path.write_text(json.dumps({"git": git_state, **payload}, indent=1))
        written.append(path)
    return written


# --------------------------------------------------------------------------- verdicts and fallbacks


def _iv(d: dict) -> str:
    return f"{d['point']:.3f} [{d['lo']:.3f}, {d['hi']:.3f}]"


def _pct(d: dict) -> str:
    return f"{100 * d['point']:+.1f}% [{100 * d['lo']:+.1f}, {100 * d['hi']:+.1f}]"


def verdict_rows(archive: Path) -> list[tuple[str, str, str]]:
    """H1–H4 as pre-registered, read from the archived verdict files (never recomputed here)."""
    e2a = json.loads((archive / "phase2a/e2a/verdict.json").read_text())
    e2b = json.loads((archive / "phase2a/e2b/verdict.json").read_text())
    h3 = json.loads((archive / "phase3a/h3_verdicts.json").read_text())
    h4 = json.loads((archive / "phase3b/e4/h4_verdict.json").read_text())
    s1, s2 = e2a["statistics"], e2b["statistics"]
    return [
        ("H1 short run (E2a)", f"truth-lost RMS change {_pct(s1['delta_truth_rms'])}; leakage {_iv(s1['leakage'])}",
         e2a["verdict"]),
        ("H2 long run (E2b)", f"participation gap {s2['participation_gap_pp']['point']:.1f} pp "
                              f"[{s2['participation_gap_pp']['lo']:.1f}, {s2['participation_gap_pp']['hi']:.1f}]; "
                              f"truth-lost RMS change {_pct(s2['delta_truth_rms'])}", e2b["verdict"]),
        ("H3a residual leakage (E3-F)", f"R = L_ZK / L_PUB {_iv(h3['H3a']['R'])}", h3["H3a"]["verdict"]),
        ("H3b anti-crowding (E3-F)", f"researcher profit ZK/PUB {_iv(h3['H3b']['P_ratio'])}", h3["H3b"]["verdict"]),
        ("H3c delay cost vs K (E3-K)", f"ΔT(5) {h3['H3c']['zero_predators']['dT_5']['point']:.1f} ticks "
         f"[{h3['H3c']['zero_predators']['dT_5']['lo']:.1f}, {h3['H3c']['zero_predators']['dT_5']['hi']:.1f}]", h3["H3c"]["verdict"]),
        ("H3 overall (E3-E)", f"truth-lost RMS change {_pct(h3['H3_overall']['rms_change'])}",
         h3["H3_overall"]["verdict"]),
        ("H4 smart execution (E4)", f"R4 = search / best simple rule {_iv(h4['H4']['R4'])}", h4["H4"]["verdict"]),
    ]


FALLBACK_COPIES = {  # key figures that already exist in the archive
    "1a_stability_true_news.png": "phase3b/shock_t/event_shock.png",
    "1b_stability_flows.png": "phase3b/shock_t/flows_shock.png",
    "1c_stability_false_news.png": "phase3b/shock_f/event_correction.png",
    "1d_stability_depeg.png": "phase3b/shock_d/flows_depeg.png",
    "1e_batching_after_news.png": "phase3b/shock_k/event_shock.png",
    "4c_search_benchmark.png": "phase3b/e4_search/search_bench.png",
    "5_manipulation_e5.png": "phase3b/e5/e5_deviation.png",
}


def export_fallbacks(data: Path, archive: Path, out: Path) -> list[Path]:
    """Every view's key figure as a PNG, so the demo survives without Streamlit (D-062)."""
    import shutil

    from tfs.core.config import load_config
    from tfs.dashboard import figures
    from tfs.search.examples import EXAMPLE_1, EXAMPLE_2, TreeGame
    from tfs.search.expectiminimax import Options
    from tfs.search.order_splitting import OrderSplittingGame, split_params
    from tfs.search.tree import explain

    out.mkdir(parents=True, exist_ok=True)
    written = []

    def save(fig, name: str) -> None:
        path = out / name
        fig.savefig(path, dpi=140)
        written.append(path)

    save(figures.verdicts_figure(verdict_rows(archive)), "0_verdicts.png")
    replay = json.loads((data / "replay.json").read_text())
    save(figures.replay_figure(replay, 23), "2_frontrun_replay_block23.png")
    policies = json.loads((data / "policies.json").read_text())["policies"]
    save(figures.policies_figure(policies), "3_public_vs_zk.png")
    plain_ab = Options(star1=False, ordering=False, transposition=False)
    save(figures.tree_figure(explain(TreeGame(), EXAMPLE_1, 1, plain_ab), "Walkthrough example 1: alpha-beta"),
         "4a_tree_example1.png")
    save(figures.tree_figure(explain(TreeGame(), EXAMPLE_2, 1, Options(ordering=False, transposition=False)),
                             "Walkthrough example 2: Star1"), "4a_tree_example2.png")
    game = OrderSplittingGame(split_params(load_config(Path("sim/experiments/configs/base.yaml"))))
    save(figures.tree_figure(explain(game, game.root(0.9, 0.2, 60.0), 1),
                             "Order-splitting game: gap 0.7 log-odds, 60 shares to buy, depth 1"), "4b_tree_real_game.png")
    for name, source in FALLBACK_COPIES.items():
        shutil.copyfile(archive / source, out / name)
        written.append(out / name)
    return written
