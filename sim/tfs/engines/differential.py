"""Differential test: do FastEngine and EvmEngine agree? (SPEC §3.3; tolerance DECISIONS D-043)

The identical sequence of ordered blocks is replayed on both engines. Running the
agents live on each engine would let microscopic rounding differences change later
decisions, and the two runs would drift apart for reasons unrelated to correctness.
Replay isolates the question: given the same transactions in the same order, do the
two implementations of the markets produce the same receipts, prices and balances?

Both engines receive the *same quantized* orders: share amounts and fees on the chain's
6-decimal grid (sells rounded toward zero). Otherwise the chain's own rounding of
amounts would nudge prices by ~1e-9 per trade. Victims that a predator deliberately
pushes to exactly their limit would then flip, and the two states would legitimately
diverge (D-043 amendment). What remains is fixed point versus float in the cost
function, plus cash rounding in the market maker's favour.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from dataclasses import dataclass, field

import math
from dataclasses import replace

import numpy as np

from tfs.core.config import SimConfig, replace_in
from tfs.core.types import Account, Bundle, Receipt, Side, Trade, Tx, Venue
from tfs.engines.evm import EvmEngine, sell_units
from tfs.engines.fast import FastEngine
from tfs.market.batch import SealedOrder
from tfs.simulation import BlockTrace, run_season

UNIT = 1e-6  # one USDC / share unit on chain
PRICE_TOL = 1e-6
CASH_TOL = 1e-4
SHARES_TOL = 1e-5
BOUNDARY = 1e-6  # a trade whose average price is this close to its limit may legitimately flip
FILL_TOL = 2 * 1e-6  # a sealed fill: the chain floors margin fills and bisects the imbalance in whole units


@dataclass
class DiffReport:
    name: str
    blocks: int = 0
    trades: int = 0
    max_price_diff: float = 0.0
    max_cash_diff: float = 0.0
    max_shares_diff: float = 0.0
    flag_mismatches: list[str] = field(default_factory=list)  # any fill/revert disagreement: a failure
    boundary_cases: list[str] = field(default_factory=list)  # decisions within one unit of a limit, pinned and reported
    max_payout_diff: float = 0.0
    max_mm_pnl_diff: float = 0.0
    captured: tuple[list[Receipt], list[Receipt]] | None = None  # (FastEngine, chain) receipts of one block
    # sealed batches only: per-fill difference, and the share tolerance derived from fills per account
    max_fill_diff: float = 0.0
    batch_shares_tol: float | None = None
    fill_excess: float = 0.0  # largest (|Δfill| − its derived allowance); must be ≤ 0

    @property
    def mm_pnl_tol(self) -> float:
        """Every trade rounds by at most one unit, always in the market maker's favour (D-043 amendment)."""
        return max(CASH_TOL, self.trades * UNIT)

    @property
    def passed(self) -> bool:
        return (
            not self.flag_mismatches
            and self.max_price_diff <= PRICE_TOL
            and self.max_cash_diff <= CASH_TOL
            and (self.batch_shares_tol is not None or self.max_shares_diff <= SHARES_TOL)
            and self.fill_excess <= 0.0  # batches: every fill and every account within its derived allowance
            and self.max_payout_diff <= CASH_TOL
            and self.max_mm_pnl_diff <= self.mm_pnl_tol
        )

    def summary(self) -> str:
        verdict = "PASS" if self.passed else "FAIL"
        shares_tol = self.batch_shares_tol or SHARES_TOL
        fill = (f"max |Δfill| {self.max_fill_diff:.1e} (worst excess over derived allowance {self.fill_excess:.1e}), "
                if self.batch_shares_tol else "")
        return (
            f"{self.name}: {verdict} | {self.blocks} blocks, {self.trades} trades | "
            f"max |Δprice| {self.max_price_diff:.2e} (tol {PRICE_TOL:.0e}), "
            f"max |Δcash| {self.max_cash_diff:.2e} (tol {CASH_TOL:.0e}), "
            f"max |Δshares| {self.max_shares_diff:.2e} (tol {shares_tol:.1e}), {fill}"
            f"payouts {self.max_payout_diff:.2e}, MM PnL {self.max_mm_pnl_diff:.2e} (tol {self.mm_pnl_tol:.1e}) | "
            f"flag mismatches {len(self.flag_mismatches)}, boundary cases {len(self.boundary_cases)}"
        )


def _balance_diffs(a: Mapping[str, Account], b: Mapping[str, Account]) -> tuple[float, float]:
    """Largest cash and share differences; an account missing on one side counts as empty."""
    empty = Account(cash=0.0)
    cash = shares = 0.0
    for k in set(a) | set(b):
        x, y = a.get(k, empty), b.get(k, empty)
        cash = max(cash, abs(x.cash - y.cash))
        for key in set(x.shares) | set(y.shares):
            shares = max(shares, abs(x.shares.get(key, 0.0) - y.shares.get(key, 0.0)))
    return cash, shares


def quantize(tx: Tx) -> Tx:
    """The order as the chain can represent it: 6-decimal amounts and fees (sells toward zero)."""
    if isinstance(tx, Bundle):
        return Bundle(tx.agent_id, tuple(quantize(t) for t in tx.trades))  # type: ignore[misc]
    units = round(tx.shares / UNIT) if tx.shares >= 0 else -sell_units(-tx.shares)
    return replace(tx, shares=units * UNIT, priority_fee=round(tx.priority_fee / UNIT) * UNIT)


def _pinned(trade: Trade, filled: bool) -> Trade:
    """Copy of a boundary trade whose limit forces the chain to the same decision as FastEngine.

    The chain compares cash in whole 6-decimal units; FastEngine compares average prices
    to ~1e-9. Within one unit of the limit their decisions can differ, so the decision is
    pinned (and counted as a boundary case) and both states stay comparable.
    """
    buying = trade.shares > 0
    if filled:
        return replace(trade, limit_price=trade.limit_price + 1e-3 if buying else max(0.0, trade.limit_price - 1e-3))
    return replace(trade, limit_price=0.0 if buying else 1e6)


def _run_fast_block(fast: FastEngine, txs: Sequence[Tx], report: DiffReport, block: int) -> tuple[list[Receipt], list[Tx]]:
    """Execute a block on FastEngine trade by trade; return its receipts and the chain's copy of the block
    (identical, except that boundary decisions are pinned)."""
    receipts: list[Receipt] = []
    chain_txs: list[Tx] = []
    for tx in txs:
        if isinstance(tx, Bundle):
            receipts.extend(fast.build_block([tx]))
            chain_txs.append(tx)
            continue
        avg = abs(fast.quote(tx.venue, tx.side, tx.shares)) / abs(tx.shares) if tx.shares else math.inf
        [r] = fast.build_block([tx])
        receipts.append(r)
        if abs(avg - tx.limit_price) <= BOUNDARY:
            report.boundary_cases.append(f"block {block}: {tx.agent_id} {tx.side.value} {tx.shares:+.4f} "
                                         f"avg {avg:.9f} vs limit {tx.limit_price:.9f} -> {'fill' if r.ok else 'revert'}")
            chain_txs.append(_pinned(tx, r.ok))
        else:
            chain_txs.append(tx)
    return receipts, chain_txs


def compare(name: str, liquidity: Mapping[Venue, float], initial_cash: Mapping[str, float],
            blocks: Sequence[Sequence[Tx]], y: int, base_fee: float = 0.0,
            capture_block: int | None = None) -> DiffReport:
    report = DiffReport(name)
    fast = FastEngine(liquidity, initial_cash, base_fee=base_fee)
    with EvmEngine(liquidity, initial_cash, base_fee=base_fee) as evm:
        for i, raw in enumerate(blocks):
            fr, chain_txs = _run_fast_block(fast, [quantize(tx) for tx in raw], report, i)
            er = evm.build_block(chain_txs)
            if i == capture_block:
                report.captured = (fr, er)
            report.blocks += 1
            report.trades += len(fr)
            for a, b in zip(fr, er):
                if a.ok != b.ok:  # boundary decisions are pinned, so any difference here is a real mismatch
                    report.flag_mismatches.append(f"block {i}: {a.trade.agent_id} {a.trade.side.value} "
                                                  f"{a.trade.shares:+.4f} (fast {a.ok}/{a.reason or 'ok'}, "
                                                  f"evm {b.ok}/{b.reason or 'ok'})")
            fp, ep = fast.prices(), evm.prices()
            report.max_price_diff = max(report.max_price_diff, *(abs(fp[v] - ep[v]) for v in fp))
            cash, shares = _balance_diffs(fast.balances(), evm.balances())
            report.max_cash_diff = max(report.max_cash_diff, cash)
            report.max_shares_diff = max(report.max_shares_diff, shares)
        fast.resolve(y)
        evm.resolve(y)
        report.max_payout_diff, _ = _balance_diffs(fast.balances(), evm.balances())
        fm, em = fast.market_maker_pnl(), evm.market_maker_pnl()
        report.max_mm_pnl_diff = max(abs(fm[v] - em[v]) for v in fm)
    return report


# --------------------------------------------------------------------------- #
# Scenarios
# --------------------------------------------------------------------------- #


def fuzz_blocks(n_blocks: int, seed: int) -> tuple[dict[str, float], list[list[Tx]]]:
    """Random traffic exercising every path: buys, sells, tight and loose limits, tips,
    revert protection and two-venue bundles."""
    rng = np.random.default_rng(seed)
    agents = [f"t{i}" for i in range(6)]
    blocks: list[list[Tx]] = []
    for _ in range(n_blocks):
        block: list[Tx] = []
        for _ in range(int(rng.integers(1, 7))):
            agent = agents[int(rng.integers(len(agents)))]
            venue = Venue.MAIN if rng.random() < 0.75 else Venue.REF
            side = Side.YES if rng.random() < 0.5 else Side.NO
            size = float(rng.exponential(8.0)) + 0.01
            if rng.random() < 0.15:  # an atomic two-venue bundle
                block.append(Bundle(agent, (Trade(agent, Venue.REF, side, size, float(rng.uniform(0.3, 1.0))),
                                            Trade(agent, Venue.MAIN, side.other, size, float(rng.uniform(0.3, 1.0))))))
                continue
            selling = rng.random() < 0.3
            limit = float(rng.uniform(0.0, 0.6)) if selling else float(rng.uniform(0.2, 1.0))
            block.append(Trade(agent, venue, side, -size if selling else size, limit,
                               priority_fee=float(rng.choice([0.0, 0.0, 0.03, 0.2])),
                               revert_protected=bool(rng.random() < 0.2)))
        blocks.append(block)
    return {a: 500.0 for a in agents}, blocks


def traced_market(cfg: SimConfig, seed: int, market: int) -> tuple[dict[str, float], list[list[Tx]], int]:
    """The ordered blocks of one simulated market (predator memories carried over from earlier markets)."""
    trace: list[BlockTrace] = []
    season = run_season(replace_in(cfg, "season.n_markets", market + 1), seed, trace_market=market, trace=trace)
    record = season.markets[market]
    return record.bankrolls, [b.plan.txs for b in trace], record.y


def run_scenarios(out: Path | None = None) -> list[DiffReport]:
    """The three Phase 2b scenarios (D-043): random fuzz, the archived predator market, a no-predator market."""
    from tfs.core.config import load_config

    configs = Path(__file__).resolve().parents[3] / "sim" / "experiments" / "configs"
    cash, blocks = fuzz_blocks(60, seed=1)
    reports = [compare("fuzz (60 blocks, fees, bundles, protection)", {Venue.MAIN: 100.0, Venue.REF: 30.0},
                       cash, blocks, 1, 0.01)]
    for name, cfg_name, seed, market, predators in [
        ("E2a predator market (seed 3, market 16)", "e2a", 3, 15, 1),
        ("season baseline, no predators (seed 1, market 1)", "season_baseline", 1, 0, 0),
    ]:
        cfg = replace_in(load_config(configs / f"{cfg_name}.yaml"), "agents.predators.count", predators)
        cash, blocks, y = traced_market(cfg, seed, market)
        reports.append(compare(name, {Venue.MAIN: cfg.market.b_main, Venue.REF: cfg.market.b_ref},
                               cash, blocks, y, cfg.mempool.base_fee))
    cash, batches = fuzz_batches(30, seed=1)
    reports.append(compare_batches("sealed batches: fuzz (30 batches, crowds, unrevealed)", 100.0, cash, batches, 1, 5,
                                   [5.0, 25.0, 125.0, 625.0]))
    zk = load_config(configs / "base.yaml")
    for key, value in [("mempool.policy", "zk_batch"), ("agents.predators.count", 1),
                       ("agents.attackers.non_reveal", 1), ("agents.attackers.free_option", 1)]:
        zk = replace_in(zk, key, value)
    cash, log, y = traced_batches(zk, 3, 15)
    reports.append(compare_batches("sealed batches: zk_batch market, metadata predator + attackers (seed 3, market 16)",
                                   zk.market.b_main, cash, log, y, zk.mempool.batch_interval, list(zk.mempool.escrow_tiers)))
    if out is not None:
        out.mkdir(parents=True, exist_ok=True)
        lines = []
        for r in reports:
            lines.append(r.summary())
            lines += [f"    boundary (pinned): {b}" for b in r.boundary_cases]
            lines += [f"    MISMATCH: {m}" for m in r.flag_mismatches]
        (out / "report.txt").write_text("\n".join(lines) + "\n")
    return reports


# --------------------------------------------------------------------------- #
# Sealed batches (Phase 3a): FastEngine.clear_batch vs SealedBatchAuction
# --------------------------------------------------------------------------- #


def quantize_sealed(o: SealedOrder) -> SealedOrder:
    """The order as the chain represents it: size in 6-decimal units, limit in millionths."""
    limit = min(1.0 - UNIT, max(UNIT, round(o.limit / UNIT) * UNIT))
    return replace(o, size=round(o.size / UNIT) * UNIT, limit=limit)


def compare_batches(name: str, b_main: float, initial_cash: Mapping[str, float],
                    batches: Sequence[tuple[Sequence[tuple[SealedOrder, float]], Sequence[tuple[str, float]]]],
                    y: int, batch_interval: int, tiers: Sequence[float]) -> DiffReport:
    """Replay the same sealed batches (main market) on both engines; compare after every clearing.

    A fill that is positive on one engine and zero on the other counts as a boundary case
    when the positive fill is below one chain unit: pro-rata rounding on the margin
    (the chain floors fills to whole units). Every other disagreement is a mismatch.
    """
    report = DiffReport(name)
    report.fill_excess = -math.inf
    liquidity = {Venue.MAIN: b_main}
    allowance_by_account: dict[str, float] = {}  # Σ of the allowances of that account's fills
    fast = FastEngine(liquidity, initial_cash)
    with EvmEngine(liquidity, initial_cash) as evm:
        evm.enable_batches(batch_interval, tiers)
        for i, (revealed, unrevealed) in enumerate(batches):
            orders = []
            for order, escrow in revealed:
                o = quantize_sealed(order)
                ok_fast, ok_evm = fast.commit(o.agent_id, escrow), evm.commit(o.agent_id, escrow, o)
                if ok_fast != ok_evm:
                    report.flag_mismatches.append(f"batch {i}: commit of {o.agent_id} fast {ok_fast} evm {ok_evm}")
                if ok_fast and ok_evm:
                    orders.append((o, escrow))
            hidden = [(a, e) for a, e in unrevealed if fast.commit(a, e) and evm.commit(a, e, None)]
            # Allowance for this batch's fills: 2 chain units, plus the pre-batch state price difference
            # magnified by the inverse slope of the average-price curve (margin fills invert it).
            p0, dp0 = fast.prices()[Venue.MAIN], abs(fast.prices()[Venue.MAIN] - evm.prices()[Venue.MAIN])
            allowance = FILL_TOL + 2 * dp0 * 2 * b_main / max(p0 * (1 - p0), 1e-6)
            fr, er = fast.clear_batch(orders, hidden), evm.clear_batch(orders, hidden)
            report.blocks += 1
            report.trades += len(fr)
            for a, b in zip(fr, er):
                if (a.trade.shares > 1e-9) != (b.trade.shares > 0):
                    tiny = max(a.trade.shares, b.trade.shares) < 2 * UNIT
                    where = f"batch {i}: {a.trade.agent_id} {a.trade.side.value} fill fast {a.trade.shares:.7f} evm {b.trade.shares:.7f}"
                    (report.boundary_cases if tiny else report.flag_mismatches).append(where)
                report.max_fill_diff = max(report.max_fill_diff, abs(a.trade.shares - b.trade.shares))
                report.fill_excess = max(report.fill_excess, abs(a.trade.shares - b.trade.shares) - allowance)
                report.max_cash_diff = max(report.max_cash_diff, abs(a.cost - b.cost))
                if a.trade.shares > 0 or b.trade.shares > 0:
                    acct = a.trade.agent_id
                    allowance_by_account[acct] = allowance_by_account.get(acct, 0.0) + allowance
            report.max_price_diff = max(report.max_price_diff, abs(fast.prices()[Venue.MAIN] - evm.prices()[Venue.MAIN]))
            cash, _ = _balance_diffs(fast.balances(), evm.balances())
            report.max_cash_diff = max(report.max_cash_diff, cash)
            # shares per account against that account's accumulated allowance (D-043 amendment 4)
            fb, eb = fast.balances(), evm.balances()
            for acct, allowed in allowance_by_account.items():
                for side in Side:
                    diff = abs(fb[acct].position(Venue.MAIN, side) - eb[acct].position(Venue.MAIN, side))
                    report.max_shares_diff = max(report.max_shares_diff, diff)
                    report.fill_excess = max(report.fill_excess, diff - (allowed + SHARES_TOL))
        fast.resolve(y)
        evm.resolve(y)
        report.max_payout_diff, _ = _balance_diffs(fast.balances(), evm.balances())
        report.max_mm_pnl_diff = abs(fast.market_maker_pnl()[Venue.MAIN] - evm.market_maker_pnl()[Venue.MAIN])
    report.batch_shares_tol = max(allowance_by_account.values(), default=0.0) + SHARES_TOL  # largest per-account allowance
    return report


def fuzz_batches(n_batches: int, seed: int) -> tuple[dict[str, float], list]:
    """Random sealed batches: both sides, tight and loose limits, identical-limit crowds, unrevealed commitments."""
    rng = np.random.default_rng(seed)
    agents = [f"t{i}" for i in range(8)]
    batches = []
    next_id = 0
    for _ in range(n_batches):
        revealed, unrevealed = [], []
        shared_limit = float(rng.uniform(0.3, 0.8))
        for agent in agents:
            if rng.random() < 0.15:
                unrevealed.append((agent, 5.0))
                continue
            if rng.random() < 0.3:
                continue
            side = Side.YES if rng.random() < 0.5 else Side.NO
            limit = shared_limit if rng.random() < 0.4 else float(rng.uniform(0.05, 0.95))
            size = float(rng.exponential(15.0)) + 0.5
            tier = next(t for t in (5.0, 25.0, 125.0, 625.0) if t >= size * limit or t == 625.0)
            size = min(size, tier / limit)
            revealed.append((SealedOrder(next_id, agent, side, size, limit), tier))
            next_id += 1
        batches.append((revealed, unrevealed))
    return {a: 5_000.0 for a in agents}, batches


def traced_batches(cfg: SimConfig, seed: int, market: int) -> tuple[dict[str, float], list, int]:
    """The sealed batches cleared in one simulated zk_batch market (main market only)."""
    log: list = []
    season = run_season(replace_in(cfg, "season.n_markets", market + 1), seed, trace_market=market, batch_log=log)
    record = season.markets[market]
    return record.bankrolls, log, record.y
