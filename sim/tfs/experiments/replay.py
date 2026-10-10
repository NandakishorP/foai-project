"""Block-by-block replay of a front-run (Phase 2a milestone).

Re-runs one season deterministically (same seed → same blocks), records every
block of one market, and explains a block in which a predator front-ran
someone:
- what was pending and when it arrived;
- what the predator could see;
- how the builder ordered the block;
- how each trade moved the price.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from tfs.core.config import SimConfig  # noqa: E402
from tfs.core.types import Bundle, Trade, Venue  # noqa: E402
from tfs.experiments import plots  # noqa: E402
from tfs.simulation import BlockTrace, MarketRecord, run_season  # noqa: E402


def _describe(trade: Trade) -> str:
    verb = "buy" if trade.shares > 0 else "sell"
    return f"{verb} {abs(trade.shares):6.1f} {trade.side.value.upper():3s} (limit {trade.limit_price:.3f})"


def explain_block(block: BlockTrace) -> str:
    """A plain-text account of one block."""
    lines = [f"Block {block.tick}: main price {block.price_before:.4f} -> {block.price_after:.4f}", ""]
    lines.append("Pending transactions (by arrival time):")
    for p in sorted(block.pending, key=lambda p: p.arrival):
        seen = [pid for pid, ids in block.visible.items() if p.tx_id in ids]
        what = "atomic bundle (arbitrage)" if isinstance(p.tx, Bundle) else _describe(p.tx)
        lines.append(f"  #{p.tx_id:<5d} t={p.arrival:.3f}  {p.sender:16s} {what}   seen by: {', '.join(seen) or '-'}")
    roles: dict[int, str] = {}
    for request, victim in block.plan.placements:
        roles[id(request.front)] = f"FRONT-RUN of #{victim.tx_id} by {request.agent_id} (bid {request.bid:.3f})"
        roles[id(victim.tx)] = f"VICTIM (#{victim.tx_id})"
        if request.back is not None:
            roles[id(request.back)] = f"BACK-RUN by {request.agent_id}"
    lines += ["", "Execution order chosen by the builder:"]
    flat = [t for tx in block.plan.txs for t in (tx.trades if isinstance(tx, Bundle) else (tx,))]
    for i, (trade, receipt) in enumerate(zip(flat, block.receipts)):
        status = "ok " if receipt.ok else f"REVERTED ({receipt.reason})"
        venue = "" if trade.venue is Venue.MAIN else " [ref venue]"
        role = roles.get(id(trade), "")
        lines.append(f"  {i + 1:2d}. {trade.agent_id:16s} {_describe(trade)}{venue}  "
                     f"{receipt.price_before:.4f} -> {receipt.price_after:.4f}  {status} {role}")
    return "\n".join(lines)


def plot_block(record: MarketRecord, block: BlockTrace, title: str, path: Path) -> Path:
    """Top: the market's price path with the replayed block marked. Bottom: the price after each trade in that block."""
    fig, axes = plots._figure(2, 1, (9.0, 6.4), gridspec_kw={"height_ratios": [2, 3]})
    top, bottom = axes[0, 0], axes[1, 0]
    ticks = np.arange(len(record.price_main))
    top.plot(ticks, record.p_avail, color=plots.SERIES[1], linewidth=plots.LINE_WIDTH, linestyle=(0, (4, 2)),
             label="p*_avail")
    top.plot(ticks, record.price_main, color=plots.SERIES[0], linewidth=plots.LINE_WIDTH, label="market price")
    top.axvline(block.tick, color=plots.MUTED, linewidth=0.8, linestyle=":")
    top.annotate(f"block {block.tick}", (block.tick, 0.97), xycoords=("data", "axes fraction"), xytext=(3, -8),
                 textcoords="offset points", fontsize=8, color=plots.MUTED)
    top.set_ylim(0, 1)
    top.set_ylabel("P(YES)")
    top.set_title(title, loc="left", fontsize=11, pad=22)
    legend = top.legend(loc="lower center", bbox_to_anchor=(0.5, 1.0), fontsize=8, frameon=False, ncols=2)
    for text in legend.get_texts():
        text.set_color(plots.INK_SECONDARY)

    front_ids = {id(r.front) for r, _ in block.plan.placements} | {id(r.back) for r, _ in block.plan.placements if r.back}
    victim_ids = {id(v.tx) for _, v in block.plan.placements}
    flat = [t for tx in block.plan.txs for t in (tx.trades if isinstance(tx, Bundle) else (tx,))]
    main = [(t, r) for t, r in zip(flat, block.receipts) if t.venue is Venue.MAIN]
    prices = [block.price_before] + [r.price_after for _, r in main]
    xs = np.arange(len(prices))
    bottom.step(xs, prices, where="post", color=plots.INK_SECONDARY, linewidth=1.0)
    for i, (trade, receipt) in enumerate(main, start=1):
        colour = plots.SERIES[1] if id(trade) in front_ids else plots.SERIES[0] if id(trade) in victim_ids else plots.MUTED
        bottom.scatter([i], [receipt.price_after], s=36 if colour != plots.MUTED else 14, color=colour, zorder=3,
                       edgecolor=plots.SURFACE, linewidth=1.0)
        if colour != plots.MUTED:
            label = "predator" if id(trade) in front_ids else "victim"
            bottom.annotate(f"{label}: {trade.agent_id}", (i, receipt.price_after), xytext=(5, 4),
                            textcoords="offset points", fontsize=8, color=plots.INK_SECONDARY)
    bottom.set_xlabel("trade in execution order (main market)")
    bottom.set_ylabel("price after trade")
    return plots._save(fig, path)


def replay(cfg: SimConfig, seed: int, market: int, out_dir: Path) -> tuple[Path, Path]:
    """Re-run the season, trace `market`, and explain its block with the largest filled front-run."""
    trace: list[BlockTrace] = []
    season = run_season(cfg, seed, trace_market=market, trace=trace)
    record = season.markets[market]
    chosen = choose_block(trace)
    if chosen is None:
        raise SystemExit(f"no filled front-run in market {market} of seed {seed}")
    out_dir.mkdir(parents=True, exist_ok=True)
    text_path = out_dir / f"replay_seed{seed}_m{market}_block{chosen.tick}.txt"
    text_path.write_text(explain_block(chosen) + "\n")
    png = plot_block(record, chosen, f"{cfg.name}: seed {seed}, market {market + 1}, block {chosen.tick}",
                     out_dir / f"replay_seed{seed}_m{market}_block{chosen.tick}.png")
    return text_path, png


def choose_block(trace: list[BlockTrace]) -> BlockTrace | None:
    """The block with the largest filled front-run (the most illustrative one)."""
    chosen, largest = None, 0.0
    for block in trace:
        receipts = {id(t): r for t, r in zip(_flat(block), block.receipts)}
        for request, _ in block.plan.placements:
            if receipts[id(request.front)].ok and request.front.shares > largest:
                chosen, largest = block, request.front.shares
    return chosen


def replay_on_chain(cfg: SimConfig, seed: int, market: int, out_dir: Path) -> Path:
    """Reproduce the replayed block on Anvil: every block of the market is sent to the real
    contracts in the builder's order (differential-test harness), and the chosen block's
    trades are printed with FastEngine and on-chain outcomes side by side."""
    from tfs.core.types import Venue as V
    from tfs.engines.differential import compare, traced_market

    trace: list[BlockTrace] = []
    run_season(cfg, seed, trace_market=market, trace=trace)
    chosen = choose_block(trace)
    if chosen is None:
        raise SystemExit(f"no filled front-run in market {market} of seed {seed}")
    cash, blocks, y = traced_market(cfg, seed, market)
    report = compare(f"{cfg.name} seed {seed} market {market + 1}", {V.MAIN: cfg.market.b_main, V.REF: cfg.market.b_ref},
                     cash, blocks, y, cfg.mempool.base_fee, capture_block=chosen.tick)
    assert report.captured is not None
    roles: dict[int, str] = {}
    for request, victim in chosen.plan.placements:
        roles[id(request.front)] = "FRONT-RUN"
        roles[id(victim.tx)] = "VICTIM"
    lines = [f"Block {chosen.tick} of market {market + 1}, seed {seed}: FastEngine vs Solidity contracts on Anvil", "",
             f"{'':3s} {'agent':16s} {'trade':38s} {'fast':>6s} {'chain':>6s} {'fast price':>11s} {'chain price':>12s}  role"]
    flat = _flat(chosen)
    for i, (trade, fr, er) in enumerate(zip(flat, *report.captured), start=1):
        lines.append(f"{i:2d}. {trade.agent_id:16s} {_describe(trade):38s} {str(fr.ok):>6s} {str(er.ok):>6s} "
                     f"{fr.price_after:11.6f} {er.price_after:12.6f}  {roles.get(id(trade), '')}")
    lines += ["", "Whole market: " + report.summary()]
    lines += [f"  boundary decision pinned: {b}" for b in report.boundary_cases]
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"replay_seed{seed}_m{market}_block{chosen.tick}_onchain.txt"
    path.write_text("\n".join(lines) + "\n")
    return path


def _flat(block: BlockTrace) -> list[Trade]:
    return [t for tx in block.plan.txs for t in (tx.trades if isinstance(tx, Bundle) else (tx,))]
