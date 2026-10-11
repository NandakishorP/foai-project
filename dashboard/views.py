"""The dashboard's pages (DECISIONS D-062). `dashboard/app.py` puts them in a navigation menu.

Every view reads precomputed results: `dashboard/data/` (built by `python -m tfs dashboard-data`)
and the archives in `docs/report/`. Only the search tree in Act 4 computes live (milliseconds).
"""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)  # tfs reads configs by paths relative to the repository root

from tfs.core.config import load_config  # noqa: E402
from tfs.dashboard import figures  # noqa: E402
from tfs.dashboard.data import verdict_rows  # noqa: E402
from tfs.search.examples import EXAMPLE_1, EXAMPLE_2, TreeGame  # noqa: E402
from tfs.search.expectiminimax import Options  # noqa: E402
from tfs.search.order_splitting import OrderSplittingGame, split_params  # noqa: E402
from tfs.search.tree import explain  # noqa: E402

DATA, ARCHIVE = ROOT / "dashboard" / "data", ROOT / "docs" / "report"
PAGES: dict = {}  # page function -> st.Page; filled in by app.py, used by the landing page's links


@st.cache_data
def load_json(path: str) -> dict:
    return json.loads(Path(path).read_text())


@st.cache_data
def load_csv(path: str) -> list[dict]:
    with Path(path).open() as fh:
        return list(csv.DictReader(fh))


def verdicts_table(names: tuple[str, ...]) -> None:
    rows = [r for r in verdict_rows(ARCHIVE) if r[0].split(" ")[0] in names]
    st.table([{"Hypothesis": h, "Measured (200 paired seeds, 95% CI)": m, "Verdict": v} for h, m, v in rows])


# --------------------------------------------------------------------------- the pages


def landing() -> None:
    st.title("Truth for Sale")
    st.markdown(
        "How much **truth** does an on-chain prediction market lose when predators front-run informed "
        "traders, and can a **zero-knowledge sealed batch auction** buy it back? A multi-agent simulation "
        "with Bayesian forecasters, a front-running predator, a ZK defense and an adversarial search.")
    st.subheader("Demo, in order")
    acts = [
        (act1, "**Act 1 — The market works.** News arrives; researchers, trend followers and the arbitrageur react; "
               "the price finds the ideal posterior. False news, a collateral depeg, and what batching does to the reaction."),
        (act2, "**Act 2 — Predators.** Block by block: a predator reads the mempool, front-runs a researcher, and the "
               "researchers crowd each other out. H1 partly supported, H2 contradicted."),
        (act3, "**Act 3 — The defense.** The same market under PUBLIC and ZK_BATCH. Sealing stops the predator "
               "(H3a supported), but batching costs accuracy (H3 contradicted): trust vs accuracy."),
        (act4, "**Act 4 — Search.** Expectiminimax with alpha-beta, Star1 and a transposition table: which branches it "
               "never looks at. Correct and fast, yet it loses to TWAP (H4 contradicted): minimax is only as good as "
               "its model of the game."),
        (verdicts, "**Verdicts and the whale.** All pre-registered verdicts; E5 manipulation."),
    ]
    for page, text in acts:
        st.markdown(text)
        st.page_link(PAGES[page], label=f"Open: {PAGES[page].title}", icon=":material/arrow_forward:")
    st.caption("Offline: precomputed results only. Fallback PNGs: dashboard/fallback/. "
               "Every number traces to docs/report/ and docs/DECISIONS.md.")


SCENARIOS = {
    "True breaking news (S-T)": ("shock_t", "shock"),
    "False news and its correction (S-F)": ("shock_f", "correction"),
    "Collateral depeg (S-D)": ("shock_d", "depeg"),
    "Batching after news: PUBLIC / commit-reveal / ZK (S-K)": ("shock_k", "shock"),
}


def act1() -> None:
    st.header("Act 1 — The market works, and how it handles shocks")
    st.markdown("One 200-tick market per seed, 200 seeds, research forced, no predator. Mean paths, flipped so the "
                "event points up. Metrics fixed in advance (D-053).")
    name = st.selectbox("Scenario", list(SCENARIOS))
    folder, event = SCENARIOS[name]
    st.image(str(ARCHIVE / "phase3b" / folder / f"event_{event}.png"), caption="Mean prices around the event")
    st.image(str(ARCHIVE / "phase3b" / folder / f"flows_{event}.png"),
             caption="Cumulative net order flow by agent kind: trend followers and the arbitrageur reacting")
    amp = [r for r in load_csv(str(ARCHIVE / "phase3b" / folder / "amplification.csv")) if r["event"] == event] \
        if (ARCHIVE / "phase3b" / folder / "amplification.csv").exists() else []
    if amp:
        st.markdown("**Trend followers on (2) minus off (0), paired, 95% CI**")
        st.table([{"point": r["point"].split("|")[0][:60], "trend push (shares)":
                   f"{float(r['trend_push']):+.1f} [{float(r['trend_push_lo']):+.1f}, {float(r['trend_push_hi']):+.1f}]",
                   "overshoot": f"{float(r['overshoot']):+.3f}" if r["overshoot"] != "nan" else "–",
                   "recovery (ticks)": f"{float(r['recovery']):+.1f} [{float(r['recovery_lo']):+.1f}, "
                                       f"{float(r['recovery_hi']):+.1f}]"} for r in amp])
    st.info("Trend followers trade with every move but barely amplify it (overshoot ≤ +0.007). In a depeg the "
            "arbitrageur withdraws (venue gap 0.12 → 0.26). Batching doubles the time to absorb news (6.9 → 13.5 ticks).")


def act2() -> None:
    st.header("Act 2 — A predator front-runs a researcher")
    replay = load_json(str(DATA / "replay.json"))
    st.caption(f"Source: {replay['source']} (the Phase 2a replay market, fixed in advance)")
    fronts = [b["tick"] for b in replay["blocks"] if b["frontrun"]]
    only = st.toggle("Only blocks with a front-run", value=True)
    choices = fronts if only else list(range(len(replay["blocks"])))
    tick = st.select_slider("Block", options=choices, value=23 if 23 in choices else choices[0])
    st.pyplot(figures.replay_figure(replay, tick))
    block = replay["blocks"][tick]
    left, right = st.columns(2)
    with left:
        st.markdown("**Pending, by arrival** (✓ = the predator could read it)")
        st.table([{"#": p["id"], "t": p["arrival"], "sender": p["sender"], "order": p["text"],
                   "seen": "✓" if p["seen"] else ""} for p in block["pending"]])
    with right:
        for pid, d in block["decisions"].items():
            st.markdown(f"**{pid}'s decision**")
            if d is None:
                st.write("no profitable front-run")
            else:
                st.write(f"Front-run {d['victim']} (#{d['victim_id']}) with {d['shares']:.1f} shares. "
                         f"P(informed) = {d['p_informed']:.2f}; expected profit {d['ev_gross']:.3f}, "
                         f"bid to the builder {d['bid']:.3f}, kept {d['ev_net']:.3f}.")
        st.markdown("**Executed, in the builder's order**")
        st.table([{"agent": e["agent"], "order": e["text"], "price": f"{e['before']:.3f} → {e['after']:.3f}",
                   "status": "ok" if e["ok"] else f"reverted ({e['reason']})", "role": e["role"]}
                  for e in block["executed"]])
    verdicts_table(("H1", "H2"))
    st.info("The predator takes about 13% of the researchers' edge. Most researcher losses come from each other: "
            "with one shared signal they send the same order at the same limit, and most revert (F-002).")


def act3() -> None:
    st.header("Act 3 — The defense: PUBLIC vs ZK_BATCH")
    policies = load_json(str(DATA / "policies.json"))["policies"]
    st.caption(" · ".join(v["source"] for v in policies.values()) + " — one market; the 200-seed results are below")
    st.pyplot(figures.policies_figure(policies))
    verdicts_table(("H3a", "H3b", "H3c", "H3"))
    st.markdown(
        "- **Sealing works against the predator:** its take falls from 13% of the researchers' edge to 0.4%.\n"
        "- **Batching costs accuracy:** the price only moves at a clearing (every 5 blocks), overshoots filled "
        "limits and lags the information. A private relay (hidden, not batched) keeps public-level accuracy.\n"
        "- **X-4 (exploratory):** marginal-price clearing removes the overshoot but hands the research rent to the "
        "market maker.\n"
        "- **Trust vs accuracy:** hide by trust (private relay: accurate) or by cryptography (ZK batch: trustless, "
        "but it lags).")


def act4() -> None:
    st.header("Act 4 — Adversarial search: the order-splitting game")
    st.markdown("MAX (the forecaster) picks a slice, MIN (the predator) a front-run, CHANCE moves the price. "
                "Grey nodes are never looked at by the pruned search; every pruned value equals the plain value.")
    trees = {"Walkthrough example 1 (alpha-beta)": "ex1", "Walkthrough example 2 (Star1)": "ex2",
             "Real game: gap 0.7, 60 shares": (0.9, 0.2, 60.0), "Real game: gap 0.5, 30 shares": (0.5, 0.0, 30.0),
             "Real game: gap 0.3, 15 shares": (1.2, 0.9, 15.0)}
    choice = st.selectbox("Tree", list(trees))
    cols = st.columns(4)
    alphabeta = cols[0].toggle("alpha-beta", value=True)
    star1 = cols[1].toggle("Star1", value=True)
    ordering = cols[2].toggle("move ordering", value=choice.startswith("Real"))
    table = cols[3].toggle("transposition table", value=choice.startswith("Real"))
    options = Options(alphabeta=alphabeta, star1=star1, ordering=ordering, transposition=table)
    spec = trees[choice]
    if spec in ("ex1", "ex2"):
        ex = explain(TreeGame(), EXAMPLE_1 if spec == "ex1" else EXAMPLE_2, 1, options)
    else:
        depth = st.radio("Depth (blocks)", [1, 2], horizontal=True)
        game = OrderSplittingGame(split_params(load_config(Path("sim/experiments/configs/base.yaml"))))
        ex = explain(game, game.root(*spec), depth, options)
    st.pyplot(figures.tree_figure(ex, choice))
    st.image(str(ARCHIVE / "phase3b" / "e4_search" / "search_bench.png"),
             caption="500 real states: nodes and time per decision. The transposition table does most of the work.")
    verdicts_table(("H4",))
    st.info("The search is correct for its game, but the game leaves out the crowd of identical researchers. "
            "TWAP's small slices avoid it (reverts 20% vs 61%). X-5 (exploratory) added the crowd and closed about a "
            "tenth of the gap: TWAP's edge is a population effect that a single agent's best response cannot find.")


def verdicts() -> None:
    st.header("Pre-registered verdicts")
    verdicts_table(("H1", "H2", "H3a", "H3b", "H3c", "H3", "H4"))
    st.caption("Rules: docs/PREREGISTRATION.md, committed before each experiment. Strict rule: a threshold counts "
               "only if the whole 95% CI clears it.")
    st.header("E5 — a whale backing the wrong outcome (adversarial worst case)")
    st.image(str(ARCHIVE / "phase3b" / "e5" / "e5_deviation.png"))
    st.markdown("The whale loses about 80% of its budget; informed researchers collect about 80% of that. After a "
                "large whale stops, the distortion persists: researchers are at their Kelly limits (limits of arbitrage).")
