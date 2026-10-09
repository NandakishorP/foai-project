# Truth for Sale — Technical Specification

> **Can a market of AI agents still find the truth when other AI agents profit from front-running and distorting it?**

An adversarial multi-agent simulation of a **fully on-chain** prediction market. Informed AI forecasters pay to research events and trade on private information; predator agents watch the public mempool, infer *who* is informed, and front-run them. We measure how much "truth" the market loses — in the short run and, crucially, in the long run once forecasters decide whether research is still worth paying for — then deploy a **ZK sealed-order batch auction** as a defense and measure what it restores **and what it costs**.

**Framing (important for honesty in the review):** Polymarket today matches orders off-chain through an operator, so it is *not* attacked via a public mempool. This project studies the design space of prediction markets that run **fully on-chain** (AMM-based markets, Augur-style designs, on-chain order flow). Polymarket data is used only to **calibrate and replay realistic scenarios**, not as a claim about Polymarket's own vulnerability.

**Central hypothesis (falsifiable):**
- **H1 (short run):** with a fixed set of informed traders, front-running mostly *redistributes* profit from informed traders to predators, and the price may reach the truth about as fast — truth lost rises only modestly.
- **H2 (long run):** when forecasters choose each epoch whether research is worth its cost, predators shrink research participation, and truth lost rises sharply. (The Grossman–Stiglitz effect.)
- **H3 (defense):** a ZK sealed batch auction restores research participation and accuracy, **at a measurable cost** in reaction speed to breaking news and execution delay.

If the data contradicts a hypothesis, that is reported as a finding — the project must not be tuned to make the hypotheses true. The numeric verdict criteria for each hypothesis are **pre-registered** in `docs/PREREGISTRATION.md` and committed before the experiment that tests it is run.

Course context: AI course, multi-agent systems, **Topic 6 — Financial Market Simulation & Algorithmic Trading (Competitive Environments)**. The topic requires: competing trading agents, **arbitrage agents**, **trend-following agents**, a **sudden shock event**, and an evaluation of **market stability**. It connects to adversarial search (minimax / alpha-beta) and utility-based decision making. Every requirement must be visibly satisfied.

---

## 1. The story (also the demo narrative)

| Act | What happens | Proof shown |
|---|---|---|
| 1. A market that works | Informed forecasters, noise traders, and arbitrageurs (linking the main market to a smaller reference venue) trade on an LMSR prediction market. | Price converges to the ideal Bayesian posterior. |
| 2. Predators arrive | Predators read the mempool, classify traders as informed, front-run them. Informed traders fight back by splitting orders using adversarial search. | Short run: profit shifts informed → predators. Long run (over a season of markets): forecasters stop researching, truth lost climbs. |
| 3. The defense | Orders become sealed commitments with a Noir ZK proof of validity; batch clears at a uniform price. Whale and oracle attacks tested too. | Predator PnL → ~0, research participation and accuracy recover — but reaction to breaking news is slower. Honest trade-off curve. |
| 4. The proof | Monte Carlo across hundreds of seeds; real Polymarket-calibrated replay; (stretch) live paper-trading. | Charts with confidence intervals. |

---

## 2. The information model (the heart of the project)

We control ground truth, so we can measure how far the market strays from it.

- Each market `m` is a binary event with hidden outcome `Y ∈ {0,1}` drawn from prior `π` (default 0.5).
- **Signals.** Information arrives as Gaussian signals centred on `+μ` if `Y=1` and `−μ` if `Y=0`. An independent signal `s ~ N(±μ, σ²)` has log-likelihood ratio `LLR(s) = 2μs/σ²`. Information strength is configured in nats (expected total LLR per market) and converted to noise variances.
- **Public news.** A Poisson stream of public signals (everyone sees them, with per-agent latency).
- **Research (private) signals, correlated** (DECISIONS D-024, D-025). Research events arrive as one Poisson stream. At each event every potential forecaster `i` receives `s_i = ±μ + u + e_i`, with a common component `u ~ N(0, τ²)` shared by all forecasters and idiosyncratic noise `e_i ~ N(0, σ_e²)`.
  - `ρ = τ²/(τ² + σ_e²)` is the correlation of two forecasters' signals given `Y`: `ρ = 0` is independent research, `ρ = 1` the textbook Grossman–Stiglitz shared signal.
  - The configured quantity is the information of all forecasters' research combined (`pooled_nats`), so sweeping `ρ` redistributes a fixed amount of information rather than changing it.
  - Research quality is the same for every forecaster; heterogeneity comes from costs (§2.1).
  - A forecaster sees its signals only in markets where it **chooses to pay** its research cost `c_i` (§2.1). The potential signals are generated for everyone from the seed regardless, so runs with different participation stay comparable.
- **Shock events.** Scheduled or random high-precision public signals ("breaking news"), optionally *false* news (signal pointing the wrong way, later corrected).
- **Two ideal prices**, both exact Bayesian posteriors: `logit(p) = logit(π) + Σ LLR(public signals ≤ t) + Σ LLR_S(research events ≤ t)`. For a group `S` of `k` researchers, the research LLR of one event is the exact correlated-Gaussian value `LLR_S = 2μ·Σ_{i∈S} s_i / (k·τ² + σ_e²)` (the group mean is sufficient). It is **not** the sum of individual LLRs, which would over-count the shared noise when `ρ > 0`.
  - `p*_full` — uses **every potential signal** (all public news + private signals of *all* potential forecasters, as if everyone researched). The best the market could ever know.
  - `p*_avail` — uses only the signals that were **actually acquired** this run (public + private signals of forecasters who paid for research).
- **Truth lost** (headline metric) = mean squared error of the market price against the full-information posterior, `E[(p_t − p*_full_t)²]`, averaged over ticks and seeds. It decomposes **additively** into two parts that explain *why* truth was lost:

  `E[(p − p*_full)²] = E[(p − p*_avail)²] + E[(p*_avail − p*_full)²]`

  - **Aggregation loss** = `E[(p − p*_avail)²]` — the market failed to absorb information that existed (e.g., slow incorporation, manipulation).
  - **Participation loss** = `E[(p*_avail − p*_full)²]` — the information never existed because forecasters stopped researching (the Grossman–Stiglitz-style channel).
  - **Why it adds up:** the cross term `2·E[(p − p*_avail)(p*_avail − p*_full)]` is zero in expectation. `p*_full` and `p*_avail` are posteriors for nested information sets, so by the tower property `E[p*_full | acquired info] = p*_avail`. The market price `p` depends only on acquired information plus randomness (noise traders, latencies, predators) that is independent of `Y` and of the unacquired signals. So `p − p*_avail` is uncorrelated with `p*_avail − p*_full`.
  - **When it holds:** across seeds, with `Y` drawn from the prior `π` and every signal drawn from the same generative model that the ideal prices use as their likelihood. It is an identity in expectation, not per run. It does **not** hold in Polymarket real-data mode, where `Y` is fixed by history (§8), and the report must say so there.
  - **Reported as** the RMS of each term (√MSE) with 95% CIs. The RMS values themselves do not add; the squared terms do. So any statement that one part "accounts for" a share of truth lost is made in MSE units.
  - **Test:** a pytest check that the cross term, averaged across many seeds, is ≈ 0 (within its standard error). If this fails, the information model or ideal-price code has a bug.

### 2.1 Endogenous research (the long-run mechanism)
- Simulations run in **seasons**: a sequence of `M` markets (default 30), each a full market lifecycle. Agents carry wealth and learned estimates across markets in a season.
- Before each market, every potential forecaster decides whether to research: research iff `EMA_i(profit per researched market) > c_i` (with small exploration probability `ε` so an agent that quit can rediscover profitability).
- Forecasters have heterogeneous costs `c_i` (lognormal around a calibrated median), so participation is a smooth fraction, not all-or-nothing. Research quality is common to all (D-025).
- **Research participation rate** over the season is a primary metric. Short-run effects = first market of a season; long-run effects = the season's final stretch after participation has settled.

Everything (signals, latencies, agent seeds) is generated from a single master seed → fully reproducible runs.

**Real-data mode (Phase 4):** a historical Polymarket market drives the scenario — its resolved outcome becomes `Y`, and its price path is used to calibrate the timing/strength of public information arrival.

---

## 3. Architecture

```
┌────────────────────────── LAB ──────────────────────────┐
│ experiment runner · Monte Carlo · tournaments · metrics │
└───────────────┬─────────────────────────────────────────┘
                │ same Engine interface
  ┌─────────────┴─────────────┐
  │ FastEngine  (pure Python) │  thousands of runs for statistics
  │ EvmEngine   (Anvil)       │  real contracts, for fidelity + demo
  └─────────────┬─────────────┘  differential test proves they agree
                │
 AGENTS ─▶ MEMPOOL (we own it: visibility + latency) ─▶ BUILDER (ordering) ─▶ BLOCK ─▶ MARKET
```

### 3.1 Simulation loop (discrete time; 1 tick = 1 block)
1. World emits signals for this tick (public news, private signals, shocks).
2. Each agent perceives what it is allowed to see (its signals + mempool view after its latency) and may submit transactions to the mempool.
3. Builder selects and orders transactions (+ bundles) into a block.
4. Engine executes the block against the market (LMSR / batch auction / oracle).
5. Metrics recorded. Repeat. Market resolves via oracle at the end.

### 3.2 The mempool (key design trick)
Agents **never** submit straight to the chain. They submit to our Python mempool, which controls:
- **Visibility:** public tx (everyone sees), private relay (only builder sees), sealed commitment (contents hidden).
- **Latency:** each agent sees mempool contents after `latency_i` (sub-block resolution modelled as an ordering of arrival times within a tick).
- **Policy modes** (the experimental variable): `PUBLIC`, `PRIVATE_RELAY`, `COMMIT_REVEAL`, `ZK_BATCH`.

### 3.3 Engines
- `Engine` abstract interface: `submit(tx)`, `build_block(ordered_txs)`, `state()`, `prices()`, `balances()`.
- `FastEngine`: pure-Python mirror of contract maths (same fixed-point rounding where it matters).
- `EvmEngine`: Anvil with automine **off**; builder sends txs in chosen order then `evm_mine`. Uses web3.py.
- **Differential test:** replay identical scenarios on both; assert prices, balances, and payouts match within a stated tolerance.

---

## 4. Market mechanisms (Solidity, Foundry)

1. **MockUSDC** (ERC-20, 6 decimals).
2. **OutcomeShares** — YES/NO shares backed 1:1 by collateral (split: 1 USDC → 1 YES + 1 NO; merge reverse; redeem winning side after resolution). Modelled on Gnosis Conditional Tokens (what Polymarket uses), simplified to binary.
3. **LMSRMarket** — cost `C(q) = b·ln(Σ exp(q_i/b))`, price `p_i = exp(q_i/b)/Σ exp(q_j/b)`. Use log-sum-exp for stability; fixed-point via PRBMath SD59x18. Max market-maker loss `b·ln 2`.
4. **SealedBatchAuction** — per batch: commit phase (commitment + ZK proof + escrow) → reveal phase (open commitment) → clear at a single uniform price; non-revealers are slashed. **Clearing by netting against the LMSR:**
   1. Take all revealed, valid orders. Buy-YES and buy-NO orders offset each other (a matched YES/NO pair is a complete set, minted from their combined payment).
   2. Route only the **net imbalance** `d = YES shares − NO shares` through the same `LMSRMarket` used in the other modes. If `d > 0`, buy `d` YES; if `d < 0`, buy `|d|` NO.
   3. Every order pays **one uniform price** `p` (per YES share; a NO buyer pays `1 − p`), set so payments exactly cover the complete sets plus the LMSR cost. That makes `p` the LMSR's average price for the net imbalance: if `d > 0`, `p = cost_of_buying_d_YES / d`; if `d < 0`, `1 − p = cost_of_buying_|d|_NO / |d|`; if `d = 0`, `p` is the current LMSR marginal price.
   4. Drop every order whose limit is violated (YES with `limit_price < p`; NO with `limit_price > p`, i.e. paying `1 − p` exceeds `1 − limit_price`), refund its escrow, and re-clear the remaining orders. Repeat until no limit is violated. Dropped orders are not re-admitted, so this terminates in at most as many rounds as there are orders.

   Keeping the same LMSR as the liquidity backstop means PUBLIC and ZK_BATCH differ only in *how orders reach the market*, not in how deep the market is.
5. **Reference venue** — a second, smaller `LMSRMarket` instance for the same event (own `b`), used by arbitrageurs (§6). No new contract; it is a second deployment.
6. **OptimisticOracle** — proposer posts outcome + bond; dispute window; disputer posts equal bond; escalation to a "vote" resolved by a stochastic honest-majority process (probability `p_vote_correct`). Loser's bond to winner (minus burn).
7. **(Stretch) CLOB settlement** — off-chain matching of EIP-712 signed orders, on-chain settlement (Polymarket model).

Foundry unit tests + invariant tests for every contract (e.g., collateral conservation: `USDC held == outstanding complete sets`; LMSR loss bounded by `b·ln 2`).

---

## 5. The ZK defense (Noir)

**What ZK adds over commit-reveal (stated precisely).** Plain commit-reveal has two weaknesses: (1) spam — junk commitments flood the batch; (2) the free option — commit to both sides and reveal only the profitable one. **Escrow + slashing deters both in either mode**, so the COMMIT_REVEAL baseline includes escrow and slashing (§5.1) and ZK is not claimed to make the free option impossible. **ZK's distinct contribution is that every commitment is proven valid and solvent at commit time**: well-formed order, escrow covers its worst-case cost, and at most one order per registered identity per batch. All of this is known before reveal, without revealing the order or which identity sent it. In plain commit-reveal, invalid or insolvent orders are only discovered at reveal, and the batch absorbs the disruption. The experiments (§5.1, E3) must measure what this difference is worth rather than assume it.

**Identity binding.** Traders register an identity commitment `id = Poseidon2(trader_secret)` in an on-chain registry, posting a registration stake (the stake is what makes creating many identities costly). The registry keeps a Merkle root of registered ids. The circuit proves membership in that root, so a commitment is tied to *some* registered identity without revealing *which* one. Predators cannot link sealed orders to an address's history.

**Circuit `sealed_order`** proves, without revealing the order:
- Private inputs: `side ∈ {0,1}`, `limit_price ∈ (0,1)` (fixed-point), `size`, `salt`, `trader_secret`, Merkle path for `id`.
- Public inputs: `commitment`, `escrow_amount`, `batch_id`, `nullifier`, `identity_root`.
- Constraints:
  - `commitment == Poseidon2(side, limit_price, size, salt, trader_secret)`
  - `side` is boolean; `0 < limit_price < 1`
  - `max_cost = side==YES ? limit_price·size : (1−limit_price)·size` and `max_cost ≤ escrow_amount`
  - `Poseidon2(trader_secret)` is a leaf under `identity_root` (Merkle membership)
  - `nullifier == Poseidon2(trader_secret, batch_id)` → one order per registered identity per batch
- Escrow uses **fixed tiers** so the escrow amount doesn't leak order size.
- Reveal must open the commitment; non-reveal → escrow slashed. The free option is deterred by slashing (as in COMMIT_REVEAL), and the nullifier caps each registered identity to one order per batch. Sybil resistance comes only from the registration stake, and the report must say so.
- Toolchain: Noir + Barretenberg (UltraHonk), auto-generated Solidity verifier. Python calls `nargo`/`bb` via subprocess for proof generation.

### 5.1 The costs of the defense (must be modelled and reported)
The defense is not free; if it wins on every metric the result looks rigged. The simulation models and measures:
- **Batch latency:** orders only execute when a batch clears (every `K` blocks, configurable). After breaking news, price can't move until the next clearing → slower **time-to-ε** after shocks. `K` is swept in E3 to draw the trade-off curve.
- **Execution uncertainty:** uniform clearing price is unknown at commit time; limit orders may not fill. Measured as **fill rate** and **execution delay**.
- **Non-reveal / griefing:** a configurable share of committers (e.g., adversarial agents) refuse to reveal, accepting the slash, to distort a batch. Measured as **non-reveal rate** and its impact on clearing.
- **Proving cost:** real proving time from `bb` is benchmarked once and fed into the sim as a per-order delay; gas cost of verification is reported from Foundry gas reports.
- **Comparison baselines:** PRIVATE_RELAY (trust the builder) and COMMIT_REVEAL with **escrow + slashing but no ZK proof**: the strongest non-ZK version, so the comparison is fair. The difference between COMMIT_REVEAL and ZK_BATCH must be measured under spam / invalid-order / free-option attacker agents, so the report can say exactly what ZK adds over the strongest simpler fix. If it adds little, that is reported.

---

## 6. Agents

Every agent class implements `perceive(observation) → act() → list[Tx]`, has a documented **PEAS** description (in its docstring and in the report), and is seed-deterministic.

| Agent | Decision logic | Course concept |
|---|---|---|
| **Informed forecaster** | Decides each market whether research is worth its cost (§2.1). Bayesian log-odds updating on its signals; target position via fractional Kelly: buy YES if belief `p > price m`, fraction `f = k·(p−m)/(1−m)` (symmetric for NO). **Executes the target via the order-splitting game (§6.1)** instead of one big order. | Utility-based agent, belief state, **adversarial search** |
| **Noise trader** | Random side/size, Poisson arrivals. Separate populations on the main market and the reference venue. | Stochastic environment |
| **Arbitrageur** | Cross-venue arbitrage between the main market and the **reference venue**: a second, smaller LMSR for the same event (own `b`, own noise traders) that receives **public news only, with a delay**. Both venues pay out on the same `Y`, so a price gap is a locked-in profit; the arbitrageur trades to close it, net of costs. Informed forecasters trade only the main market. (No YES+NO parity arbitrage: LMSR prices always sum to 1 by construction.) | Informed search / utility |
| **Trend follower** | Momentum on price (EMA crossover / time-series momentum). | Required by Topic 6 |
| **Whale manipulator** | Budget `B`, target price `p_target`, defends it over a window. | Adversarial |
| **Predator (MEV)** | Watches the mempool; keeps a per-address **Beta posterior over "is informed"**, updated from each trade's markout (price move after the trade). Front-runs (and optionally back-runs) when `P(informed)·E[move] > cost + builder tip`. | Bayesian inference, partial observability |
| **Builder** | Orders txs to maximize its revenue (priority fees + bundle bids); may run its own predator strategy (integrated builder). | Search / optimization |
| **Oracle proposer / disputer / attacker** | Plays the bond game. Attacker holds a market position and profits from a false resolution. Small game solved exactly by **expectiminimax** over {propose truthfully, propose falsely, dispute, don't dispute} with chance nodes for the vote. Secondary to §6.1. | Adversarial search (secondary) |
| **(Stretch) LLM forecaster** | Reads real headlines, outputs a probability, trades like the informed forecaster. | Modern agentic AI |

### 6.1 The order-splitting game (headline adversarial search)
The informed forecaster wants to move its position by `Q` shares within a horizon of `H` blocks before its edge decays (others learn the same news). Each slice it sends is visible to predators (in PUBLIC mode), who react.

- **Players:** MAX = informed trader; MIN = predator (modelled as the strongest predator present).
- **MAX actions per block:** slice size `q_t ∈ {0, Q/8, Q/4, Q/2, remaining}`.
- **MIN actions per block:** front-run size `f ∈ {0, small, large}` or back-run.
- **CHANCE nodes:** noise-trader flow and possible public news arrival in that block (discretised into a few outcomes with probabilities).
- **Payoff (zero-sum approximation):** MAX's expected execution profit = `Σ (belief − execution price) × filled qty` using LMSR price impact; MIN receives the negative.
- **Algorithm:** depth-limited **expectiminimax with alpha-beta pruning on MAX/MIN layers**, move ordering (try larger slices first after news, smaller otherwise), a transposition table keyed on (remaining qty, LMSR state bucket, depth), and a heuristic evaluation at the depth cut-off: `remaining_qty × expected adverse impact`.
- **Baselines:** naive (all at once), TWAP (equal slices), random.
- **Reported:** profit vs baselines across predator strengths; **nodes expanded with vs without alpha-beta pruning** and runtime vs depth (a clear course-concept demonstration).

---

## 7. Experiments

All experiments are config-driven (YAML), run on FastEngine with N seeds (default 200), and report means with 95% confidence intervals.

| ID | Question | Independent variable | Key metrics |
|---|---|---|---|
| E1 | Without predators, does the market find the truth? | # informed, signal precision, `b`, research correlation `ρ` (robustness) | truth lost, aggregation loss, share of research information priced, Brier, time-to-ε / settled share |
| E2a | **Short run:** what do predators do with participation fixed? (tests H1) | # predators, predator latency | truth lost, informed PnL, predator PnL, leakage ratio |
| E2b | **Long run:** what happens when research is a choice? (tests H2) | # predators, research cost distribution; full seasons | participation rate over the season, participation loss, truth lost |
| E3 | Which defense works, and what does it cost? (tests H3) | mempool policy: PUBLIC / PRIVATE_RELAY / COMMIT_REVEAL / ZK_BATCH; batch interval `K` | all of the above + time-to-ε after news, fill rate, execution delay, non-reveal impact → **trade-off curve** |
| E4 | Does smart execution help? | splitting strategy: naive / TWAP / expectiminimax; predator strength; search depth | informed PnL, leakage ratio, nodes expanded with/without pruning |
| E5 | Cost of manipulation | whale budget, # arbitrageurs | deviation size × duration, whale loss |
| E6 | When does oracle attack pay? | bond size, attacker position, `p_vote_correct` | attack success rate, attacker EV |
| E7 | Which strategy mix is stable? | strategy profiles (tournament) | empirical payoff matrix, Nash equilibrium (replicator dynamics) |
| Shock | Market stability under shock (Topic 6 requirement) | true / false breaking news; collateral stablecoin depeg | recovery time, max deviation, liquidity withdrawal, trend-follower amplification |

**Metrics glossary**
- *Truth lost*: `E[(p_t − p*_full_t)²]`, reported as RMS; decomposed additively (in MSE units) into *aggregation loss* and *participation loss* (§2).
- *Research participation rate*: fraction of potential forecasters researching, per market across a season.
- *Brier score*: `(p_T − Y)²` and time-averaged.
- *Time-to-ε*: first tick after a news shock where `|p_t − p*_avail_t| < ε` and stays there.
- *Informed PnL / Predator PnL / Builder revenue / Noise-trader loss*.
- *Leakage ratio*: share of informed traders' theoretical edge captured by predators.
- *Fill rate / execution delay / non-reveal rate*: costs of batch mechanisms (§5.1).

**Reporting rule:** every hypothesis (H1–H3) gets an explicit verdict — supported, partly supported, or contradicted — with the evidence. Verdicts are decided by the criteria in `docs/PREREGISTRATION.md`, which are committed before the corresponding experiment runs and not edited afterwards (any later change is logged in `docs/DECISIONS.md` and disclosed in the report). Contradicted results are reported, not tuned away.

---

## 8. Real-world layer (Phase 4)

Reminder of framing: Polymarket matches orders off-chain, so we do **not** claim its users are front-run via a mempool. Real data answers: *"if a market with this real information flow ran fully on-chain, what would happen?"*

- **Polymarket historical replay:** fetch market metadata and price history from Polymarket's public APIs (Gamma API for markets, CLOB API price history — verify endpoints before building), cache to disk as parquet, use to calibrate scenarios (news timing and strength, volatility, volume).
- **Showcase replays:** e.g., 2024 US election whale period (for the manipulation experiment); a Fed-rate-decision market (for the breaking-news shock).
- **(Stretch) Live paper-trading:** forecaster agents watch live Polymarket markets and place *imaginary* trades; track accuracy vs the real market. **No real-money trading.**

---

## 9. Dashboard ("mission control")

Streamlit + Plotly (unless decided otherwise):
- Price vs `p*_avail` vs `p*_full` vs truth, over time.
- Block-by-block replay: mempool contents, builder ordering, who front-ran whom.
- Agent PnL leaderboard.
- Season view: research participation rate falling (PUBLIC) vs holding (ZK_BATCH) across markets.
- Toggle mempool policy (PUBLIC ↔ ZK_BATCH) and re-run the same seed side-by-side.
- Order-splitting game tree visualization (expectiminimax, pruned branches greyed out, node counts).
- Experiment result charts with confidence intervals.

---

## 10. Repository layout

```
truth-for-sale/
├── CLAUDE.md
├── README.md
├── docs/
│   ├── SPEC.md            # this file
│   ├── DECISIONS.md       # running log of design decisions
│   ├── PREREGISTRATION.md # hypothesis verdict criteria, committed before experiments
│   └── report/            # written submission
├── contracts/             # Foundry project
│   ├── src/  test/  script/
├── circuits/
│   └── sealed_order/      # Noir circuit + tests
├── sim/                   # Python package `tfs`
│   ├── core/              # types, config, RNG, information model
│   ├── market/            # LMSR, batch auction, oracle (Python mirrors)
│   ├── engines/           # FastEngine, EvmEngine
│   ├── mempool/           # mempool policies, builder
│   ├── agents/
│   ├── metrics/
│   ├── data/              # Polymarket fetch/cache
│   ├── search/            # expectiminimax + alpha-beta (order splitting, oracle game)
│   └── experiments/       # runner + YAML configs (E1–E7, shocks)
├── dashboard/
└── tests/                 # pytest (incl. differential tests)
```

---

## 11. Phases & milestones

| Phase | Scope | Milestone (must be demonstrable) |
|---|---|---|
| **1. The world** | Info model with `p*_full` / `p*_avail`; seasons + endogenous research (§2.1); FastEngine, LMSR (Python); main market + reference venue; informed/noise/arb/trend agents (informed uses simple execution for now); metrics incl. MSE decomposition + cross-term test; experiment runner; E1 | Plot: price converges to `p*_avail`; participation stable without predators; E1 results with CIs; cross term ≈ 0 across seeds |
| **2a. The predators (FastEngine)** | Mempool + builder; predator agent; commit `PREREGISTRATION.md` (H1, H2); E2a + E2b — all on FastEngine | Block-by-block front-run replay; season chart showing participation collapsing under predators (or not — report honestly); H1/H2 verdicts per pre-registered criteria |
| **2b. On-chain fidelity** | Contracts (shares, LMSR, oracle) + Foundry unit/invariant tests; EvmEngine on Anvil; differential test FastEngine ↔ EvmEngine | Differential test passes on replayed scenarios; same front-run replay reproduced on Anvil |
| **3. The fight** | Order-splitting expectiminimax (§6.1) + E4; batch auction contract (netting clearing, §4) + identity registry; Noir circuit (with identity binding) + verifier; commit-reveal (escrow + slashing) & ZK modes with all costs (§5.1); pre-register H3, then E3 trade-off curve; whale (E5); oracle game (E6); shock scenarios | Same seed PUBLIC vs ZK_BATCH: predator PnL ≈ 0, participation recovers, but slower reaction to news; alpha-beta node-count chart |
| **4. Real world & polish** | Polymarket-calibrated replay; dashboard; E7 tournament; written report with H1–H3 verdicts | Full demo run-through; report draft |
| Stretch | LLM forecaster, live paper-trading, CLOB | — |

The core story is complete after Phase 3. Phase 4 is the "wow" layer.

---

## 12. Tools & technologies (to be listed in the submission)

Python 3.12 · NumPy · SciPy · pandas · web3.py · pytest · Hypothesis · Solidity 0.8.x · Foundry (forge, anvil) · OpenZeppelin · PRBMath · Noir · Barretenberg (UltraHonk) · Poseidon2 · Streamlit · Plotly · Polymarket public APIs · (stretch) an LLM API.

---

## 13. Prior work & positioning (never claim "first")

The individual ideas are established; the contribution is **combining them in an on-chain prediction market and measuring the long-run effect on accuracy**. The report should cite and position against:
- **Informed trading & market microstructure:** Kyle (1985) — informed trader splitting orders; Glosten & Milgrom (1985) — adverse selection and spreads.
- **Information acquisition paradox:** Grossman & Stiglitz (1980) — if prices reveal information for free, nobody pays to acquire it.
- **Prediction markets:** Hanson's LMSR (2003/2007); Wolfers & Zitzewitz (2004) on prediction markets as aggregators.
- **MEV:** Daian et al., "Flash Boys 2.0" (2019) — front-running and priority gas auctions on Ethereum.
- **Batch auctions / sealed order flow:** Budish, Cramton & Shim (2015) — frequent batch auctions; existing systems such as CoW Protocol (batch auctions), Penumbra (sealed-bid batch swaps), Shutter (threshold-encrypted mempool).
- **Empirical game-theoretic analysis:** Wellman (2006).

Verify each citation's details before putting it in the report.

**Expected examiner questions to prepare for:** Why not threshold encryption instead of ZK? (Answer: different trust model — needs a keyper committee; ZK + escrow needs no committee but costs proving time; compare in the report.) Isn't the result built in? (Answer: H1 predicts *little* short-run harm; the harm only appears through the participation channel, and the defense's costs are measured.) Does this apply to Polymarket? (Answer: §8 framing.)

---

## 14. Non-goals
- No real-money trading, no mainnet/testnet deployment.
- Not a production exchange; the contracts exist to make the simulation faithful.
- Not a general MEV framework — MEV is studied only inside the prediction market. 