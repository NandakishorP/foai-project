# Truth for Sale — How much truth does an on-chain prediction market lose to front-running, and can zero-knowledge batching buy it back?

*DRAFT. Sections 4–6 are drafted for owner review. Sections 1, 2, 3, 7, 8, 9 and the appendix follow after that review. Every number is copied from an archive named next to it (paths are relative to `docs/report/`). Verdicts follow `docs/PREREGISTRATION.md`. Everything that must sit next to a verdict is in `DISCLOSURES.md` and is repeated here where it applies. Decision numbers (D-…) refer to `docs/DECISIONS.md`.*

---

## 1. Abstract
*(after review of sections 4–6)*

## 2. Problem and framing
*(after review: the question, hypotheses H1–H4, the Topic 6 requirement mapping, and the full list of tools)*

## 3. Prior work
*(after review: verified citations only)*

---

## 4. System design

### 4.1 Architecture
The system is a discrete-time multi-agent simulation (1 tick = 1 block) with two interchangeable execution engines:

```
experiment runner (YAML configs, 200 seeds, paired bootstrap)
        │
        ▼
 world (signals) ──▶ agents ──▶ mempool (visibility, latency, policy) ──▶ builder (ordering) ──▶ engine ──▶ market
                                                                                       │
                                                         FastEngine (Python) ◀── differential test ──▶ EvmEngine (Anvil + Solidity)
```

- **Each tick:**
  1. the world publishes the tick's signals (all drawn in advance into a `SignalTape`);
  2. every agent perceives only what it may see and returns transactions;
  3. the mempool decides who can read pending transactions, and when;
  4. the builder orders the block;
  5. the engine executes it.
- **One master seed, many streams.** Each source of randomness (signals, noise orders, research decisions, …) has its own named stream. Runs that differ in one setting (say, a predator) therefore see identical signals and noise. That makes paired comparisons possible.
- **FastEngine and EvmEngine** implement the same `Engine` interface.
  - FastEngine (pure Python) runs the Monte Carlo experiments.
  - EvmEngine runs the same blocks on the Solidity contracts on a local Anvil chain, with automine off; the builder mines each block.
  - A differential test replays identical scenarios on both. It passes on five scenarios: max |Δprice| ≤ 5e-16 for continuous trading and ≤ 1.8e-8 for sealed batches (`phase2b/report.txt`, `phase3a/difftest_report.txt`; D-044, D-050).
- **Mempool policies** (the experimental variable):
  - `PUBLIC`: pending transactions readable after each observer's latency;
  - `PRIVATE_RELAY`: only the builder sees them;
  - `COMMIT_REVEAL`: sealed orders with escrow and slashing;
  - `ZK_BATCH`: sealed orders with a validity proof (§4.4).

### 4.2 The market
- **Main market.** A binary LMSR with liquidity b = 100. Cost C(q) = b·ln(e^{q_YES/b} + e^{q_NO/b}); price p = sigmoid((q_YES − q_NO)/b). The market maker's loss is bounded by b·ln 2.
- **Reference venue.** A second, smaller LMSR (b = 30) on the same event. It sees public news only, five blocks late. Cross-venue arbitrage links the two (D-005).
- **Sealed-batch clearing** (D-046). Every K = 5 blocks the revealed buy orders clear at one uniform price.
  - Matched YES/NO pairs become complete sets; only the net imbalance trades with the LMSR.
  - The price is the fixed point at which the LMSR's *average* price for the imbalance equals the price.
  - Orders whose limit equals the clearing price are filled pro rata.
  - This replaces the SPEC's original "drop every violated order" rule (D-004). With identical researcher limits, that rule empties whole batches.
  - The exploratory X-4 replaces the average price by the post-trade *marginal* price (§6.3).

### 4.3 Agents (PEAS)
Every agent class carries its PEAS description in its docstring (`sim/tfs/agents/`).

| Agent | Performance | Environment | Actuators | Sensors | Decision logic (course concept) |
|---|---|---|---|---|---|
| Informed forecaster | Trading profit net of research cost; over a season, the research decision | Main LMSR, public news, own research signals, other traders | Buy/sell YES/NO on the main market, one order per block. The slice size is set by a slice rule (E4) | Own research signals (at once), public news (1 block late), price, own account | Bayesian log-odds belief; fractional Kelly target (utility); research iff EMA(profit) > cost; order splitting by expectiminimax (adversarial search) |
| Public-news trader | Trading profit | One venue, public news, other traders | Buy/sell on its venue | Public news (late), its venue's price, own account | Bayesian belief from public news; fractional Kelly |
| Noise trader | None optimised (exogenous reasons) | One venue | Random market buys | None (the clock, in a depeg) | Poisson arrivals, random side and size (stochastic environment) |
| Arbitrageur | Locked-in profit with limited capital | Both venues | Atomic two-leg bundles | Both prices, own cash, collateral value | Closed-form optimal size; under a depeg, worst-case dollar payoff (utility, search) |
| Trend follower | Trading profit | Main market | Market buy/sell orders | Price history, own account | Fast/slow EMA crossover (Topic 6) |
| Predator (MEV) | Profit net of fees and builder bids | Main market, public mempool, builder | Front-run requests (optionally back-runs); unwinds | Pending transactions after its latency; executed trades; price | Beta posterior per address from post-trade markouts (belief state); expected-value front-run sizing net of exit slippage (utility) |
| Metadata predator | Trading profit | Sealed-batch market, commit metadata | One sealed order per batch | Commit metadata (sender, tier), revealed fills, price | Per-address markout average; copy-trades informed senders (H3a's adversary) |
| Attackers (non-reveal, free-option, spam) | None optimised | Sealed-batch market | Sealed commitments, reveal choices | Public reveals (free option) | Stress the defense's costs (SPEC §5.1) |
| Whale | Holds the price at a target (its objective); loss reported | Main market | Buy orders | Price, clock, own cash | Moves the price to the target each block within its budget (E5) |

The block **builder** orders transactions by priority fee, then arrival, and sells a front-run slot for a bid. It is part of the environment, not an agent with goals.

### 4.4 Contracts and the zero-knowledge circuit
**Solidity** (Foundry, Solidity 0.8.27, OpenZeppelin v5.1.0, PRBMath v4.1.0; `contracts/src/`):

| Contract | Role |
|---|---|
| `MockUSDC` | 6-decimal collateral |
| `OutcomeShares` | binary conditional tokens: split, merge, redeem (modelled on Gnosis Conditional Tokens) |
| `LMSRMarket` | the LMSR in SD59x18 fixed point, log-sum-exp for stability |
| `TradeRouter` | fees, atomic bundles, revert protection (the builder's view of a block) |
| `OptimisticOracle` | propose, dispute, settle |
| `IdentityRegistry` | staked identity registration; Poseidon2 Merkle tree of identities (depth 8) |
| `SealedBatchAuction` | commit (with proof), reveal (Poseidon2 opening), clear (the price ladder of §4.2 in fixed point); refunds and slashing |
| `SealedOrderVerifier` | the Barretenberg-generated UltraHonk verifier |

- **47 Foundry tests**, including invariant tests: collateral equals complete sets, holdings match the LMSR state, market-maker solvency within b·ln 2, price in [0, 1]. They also include a fuzzed batch test and a real-proof end-to-end test.
- **Gas** (median): LMSR buy about 158k, sell about 128k, arbitrage bundle about 456k; proof verification about 2.84M.

**Circuit `sealed_order`** (Noir 1.0.0-beta.16, Barretenberg v2.1.8 UltraHonk; `circuits/sealed_order/src/main.nr`). Without revealing the order or which identity sent it, the proof shows that:
1. the commitment opens to a well-formed buy order: side ∈ {YES, NO}, 0 < limit < 1, size > 0. The commitment is Poseidon2(side, limit, size, salt, secret);
2. it is solvent: limit × size ≤ the posted escrow, which comes in fixed tiers {5, 25, 125, 625} USDC so it does not leak the size;
3. the sender is a registered identity: Poseidon2(secret) is in the registry's Merkle tree;
4. the nullifier equals Poseidon2(secret, batch_id), so each identity gets one order per batch.

- **Tests:** ten circuit tests (the valid case and each invalid case). The Poseidon2 implementation on chain is cross-checked against Noir's.
- **Performance:** proving takes 0.28 s (median; p95 0.29 s; Apple M4 Pro).
- **Deployability:** the generated verifier fits Ethereum's 24,576-byte contract-size limit only when compiled with optimizer runs = 1 (23,723 bytes). The local chain enforces the limit (D-052).

**ZK compared with plain commit-reveal.** Both use escrow and slashing. ZK's distinct contribution is that every commitment is proven valid and solvent *at commit time*. In commit-reveal, an insolvent or invalid order is only discovered at reveal (SPEC §5).

### 4.5 Adversarial search: the order-splitting game (SPEC §6.1)
- **The game, replanned every block.** A forecaster with R shares still to buy:
  - **MAX** picks a slice (0, R/8, R/4, R/2 or R).
  - **MIN, the predator**, picks a front-run (none, half or the most it can take). It only considers front-runs that are profitable under its own EV formula, using the beliefs the real predator holds (D-053, D-054).
  - **CHANCE:** noise traders, public news and other traders closing the gap move the price.
- **The search.** Depth-limited expectiminimax with:
  - alpha-beta pruning at MAX/MIN nodes;
  - Star1 pruning at chance nodes, which uses value bounds;
  - move ordering;
  - a transposition table, made exact by keeping states on a grid.
- **Correctness.** Every combination of the speed-ups returns the plain expectiminimax value exactly. This holds on 620 random games with repeated states and on the real game (`tests/test_expectiminimax.py`, `tests/test_order_splitting.py`).
- **Walkthrough:** `walkthroughs/search.md` gives a plain-language walkthrough with line references and two hand-solvable trees, which are also tests.

---

## 5. Methodology

### 5.1 Information model (SPEC §2)
- **The outcome:** each market has a hidden binary outcome Y.
- **Signals.** Information arrives as Gaussian signals centred on +μ (Y = 1) or −μ (Y = 0):
  - **public news:** a Poisson stream, about 10 items and 2 nats per market;
  - **research signals:** about 10 events and 2 nats pooled, received only by forecasters who pay the research cost;
  - **one breaking-news shock:** 1 nat at tick 100.
- **Correlated research.** Signals are correlated across forecasters (ρ); the exact posterior of a group uses the group's mean signal (D-024).
- **Two ideal prices,** both exact Bayesian posteriors:
  - p*_full uses every potential signal: the best the market could know;
  - p*_avail uses only the signals actually bought.

### 5.2 Truth lost and its decomposition
- **Definition:** truth lost = E[(p_t − p*_full,t)²], reported as RMS.
- **The decomposition** (D-001): E[(p − p*_full)²] = E[(p − p*_avail)²] + E[(p*_avail − p*_full)²].
  - The first term is **aggregation loss**: information existed but was not priced.
  - The second is **participation loss**: information was never bought.
- **The cross term** vanishes in expectation, because p*_avail is the conditional expectation of p*_full given the acquired information. A test checks it is zero across seeds, and a deliberately leaky market fails that test.
- **When the decomposition is not claimed:** scenarios that force a shock's status condition on a rare event, so the decomposition is not claimed for them.

### 5.3 Calibration (pre-declared rules)
- **First attempt (F-001).** With independent research signals (ρ = 0), the market priced only about 9% of the research information. Kelly traders move the price towards the *average* belief.
- **Round 1 (D-026, D-028).** A pre-declared calibration grid over ρ, informed capital and research cost found no point meeting both criteria: steady-state participation 50–70% and at least 60% of research information priced.
- **Round 2 (D-029, D-030; 72 points).** Only ρ = 1 met both criteria. Frozen values:
  - **ρ = 1:** one shared research signal, the Grossman–Stiglitz textbook case;
  - informed bankroll 2 × b per market;
  - median research cost 1.716.
- **The resulting baseline:** 55% steady-state participation and 70% of research information priced.
- **Frozen for every later experiment,** with one consequence: at ρ = 1 a researcher leaving removes informed capital (aggregation loss), not information (participation loss).

### 5.4 Pre-registration and statistics
- **Pre-registration.** Verdict rules for H1–H4 were committed before the experiment they judge (`docs/PREREGISTRATION.md`; commits `b803d95`, `ab7e174`, `cfd0294`), with thresholds and the reference configuration. Any change made after a run started is logged in DECISIONS and disclosed.
- **Paired design.** Every comparison uses the same 200 master seeds, so signals and noise orders are identical between twins.
- **Confidence intervals.** 95% paired-bootstrap intervals: 10,000 resamples of seeds, bootstrap seed 0, percentile method. Statistics that combine several cells resample the seeds jointly.
- **The strict rule:** a threshold counts only if the whole CI clears it.
- **Exploratory and descriptive results** (X-1 to X-5, the shock scenarios, E5) are labelled as such and never change a verdict.

---

## 6. Results by act

### 6.1 Act 1 — The world works (E1; `phase1_milestone/`)
- **E1 setting:** single markets, full participation, 200 seeds.
- **Baseline accuracy:** truth-lost RMS 0.035 [0.034, 0.036]. The market prices 96% of the research information, and 90% of runs settle within ε of p*_avail after the shock.
- **ρ sweep:** the shared-signal baseline is far more accurate than independent research. Truth-lost RMS falls from 0.171 (ρ = 0) to 0.035 (ρ = 1).
- **Seasons with a research choice** (30 markets): participation falls from 100% to a steady 55% [52, 59] by markets 21–30.
- **Decomposition check:** the cross term over the season is 2.0e-5 [−6.5e-5, 1.1e-4], consistent with 0.

### 6.2 Act 2 — Predators (H1, H2; `phase2a/`)
The reference predator's parameters were fixed before any run (D-034).

| Hypothesis | Measured (200 paired seeds) | Verdict |
|---|---|---|
| H1 (E2a, markets 6–30, research forced) | Truth-lost RMS +3.4% [+3.2, +3.7]; leakage 0.130 [0.123, 0.138] (threshold ≥ 0.30) | **partly supported** |
| H2 (E2b, markets 21–30, research endogenous) | Participation gap 6.0 pp [4.5, 7.6]; truth lost +11% [+6, +17] | **contradicted** |

- **Where the edge went.** The predator nets about 5.8 per market; informed profit falls from 59.3 to 51.6 per market.
- **Sensitivity, next to H2.** A more aggressive viable predator (r = 0.5, X-1) gives 10.4 pp and +18%, which would read "partly supported". The pre-registered verdict stands.
- **Finding F-002:** most research rent is lost to researchers competing on the same signal. 56% of their trades revert on their own limits with no predator present. The predator taxes a small pie.
- **On-chain fidelity (Phase 2b).** The archived front-run (seed 3, market 16, block 23; `phase2a/replay/`) replays on the Solidity contracts trade for trade.

### 6.3 Act 3 — The defense (H3, X-4; `phase3a/`, `exploratory/x4/`)

| Hypothesis | Measured (200 paired seeds, K = 5) | Verdict |
|---|---|---|
| H3a residual leakage (vs a metadata-reading predator) | R = L_ZK / L_PUB = 0.03 [−0.06, 0.12] | **supported** |
| H3b anti-crowding | Researcher profit ZK / PUBLIC 0.85 [0.83, 0.86]; unfilled share +4.5 pp | **contradicted** |
| H3c delay cost vs K | ΔT(5) = 17.2 ticks [16.5, 17.9] (above 3K = 15); not increasing in K | **contradicted** |
| H3 overall (E3-E, endogenous research) | Truth-lost RMS +43% [+36, +51]; participation −2.9 pp [−4.8, −1.0] | **contradicted** |

- **Sealing works against the predator.** The predator's take falls from 13% of the researchers' edge to 0.4%, a CI that includes 0.
- **Batching costs accuracy.** Under the pre-registered clearing rule, the market price *overshoots* every filled limit and *lags* the information: price moves only at a clearing, once every 5 blocks (D-051, refined in D-058).
- **Hiding without batching keeps accuracy.** PRIVATE_RELAY keeps public-level accuracy (truth MSE 0.0013) and the predator earns nothing. The accuracy loss comes from batching, not from hiding.
- **The 2×2 decomposition** (descriptive):
  - hiding orders from the predator is worth +0.75 per researcher-market;
  - the batching side costs −0.92, so the crowd term dominates.
- **Costs** (SPEC §5.1):
  - proof 0.28 s; verification about 2.84M gas;
  - execution delay about 4 ticks at K = 5;
  - fill rate rises with K, from 0.44 (K = 1) to 0.68 (K = 20);
  - truth MSE also rises with K, from 0.008 to 0.040.
- **The conservative proving delay.** The pre-registered 1-tick delay is conservative, since a 0.28 s proof fits inside a block. Commit-reveal (zero delay) is the realistic ZK outcome: researchers' unfilled share 0.28 instead of 0.57, with the same accuracy.
- **Attackers:**
  - the non-reveal griefer and the spammer lose their whole bankroll and change no one else's outcome (spam is impossible under ZK);
  - the free-option pair loses about 330 per market.
- **Exploratory X-4: marginal-price clearing.**
  - It removes the overshoot and lowers ZK's truth-lost RMS by 15% [14.7, 15.6], but ZK stays about 2.7× the public level, because the lag remains.
  - It moves the research rent to the market maker: about 47–50 per market; researcher profit falls from 5.0 to 1.2 per researcher-market.
- **Conclusion of Act 3: trust vs accuracy.**
  - Hiding by trust (a private relay) is accurate.
  - Hiding by cryptography (ZK batches) is trustless, but batching lags. The clearing rule only decides whether the price overshoots (average) or the market maker takes the rent (marginal).
  - Untested future work: a hybrid rule, with the limit check at the marginal price, average-price charging and a pro-rata rebate.

### 6.4 Act 4 — Smart execution (H4, E4-search, X-5; `phase3b/e4*`, `exploratory/x5/`)

**The algorithm: correct and efficient** (500 states the forecasters searched; every pruned value equals the plain value to within 2.2e-16):

| depth | plain | + alpha-beta | + Star1 | + ordering | + transposition table |
|---|---|---|---|---|---|
| 3 | 7,660 nodes · 17 ms | 7,388 | 7,057 · 20 ms | 3,911 | **1,486 · 4.6 ms** |
| 4 | 89,862 · 197 ms | 86,425 | 82,348 · 236 ms | 39,045 | **3,469 · 10.5 ms** |

- **The transposition table does most of the work**, because grid states recur.
- **Alpha-beta alone saves little.** The predator usually has a single allowed front-run, so MIN nodes rarely offer alternatives to cut.
- **Star1 removes nodes but costs more time than it saves.** This is reported, not tuned away.

**The strategy: H4 contradicted** (pre-registered, 200 paired seeds):

| rule | researcher PnL per researcher-market, 1 predator | leakage | researcher reverts |
|---|---|---|---|
| capped (Phase 1–3a rule) | 5.16 | 0.130 | 61% |
| naive (all at once) | 4.56 | 0.234 | 65% |
| **TWAP** (1/5 per block) | **5.62** | **0.083** | **20%** |
| random | 4.89 | 0.186 | 38% |
| expectiminimax | 5.07 | 0.147 | 50% |

- **The verdict statistic:** R4 = search / best simple rule = 0.901 [0.890, 0.912], entirely ≤ 1.00, so **contradicted**.
- **Search loses on leakage too:** it loses more to the predator than the capped rule (+1.7 pp [+1.1, +2.4]).
- **Minimax is only as good as its model of the game.** The search is correct for its game, but the game leaves out the main force. It models one predator and a fixed competitor push; in the market, nine researchers with the same signal send the same order at the same limit in the same block. TWAP's small slices avoid that crowd, and beat the search even with no predator (0.970 [0.963, 0.975]). This risk was stated in the pre-registration.
- **Private optimum, social cost.** TWAP is the best private response, but it slows price discovery: truth MSE is about 65% higher than the capped rule's without predators. That is an externality between the individual and the market optimum.
- **Exploratory X-5: a crowd-aware search** (completed about 7 hours past its time box; D-061).
  - The game gains the measured crowd trading ahead of the slice.
  - It earns 0.917 [0.907, 0.927] of TWAP, against 0.906 for the plain search at the same depth. It closes about a tenth of the gap.
  - A single crowd-aware deviator gains nothing detectable: +0.12 [−0.17, +0.41].
  - TWAP's advantage looks like a population effect, which a best response to the observed crowd cannot find.

### 6.5 Market stability under shocks (Topic 6; descriptive; `phase3b/shock_*`)
- **Setting:** one 200-tick market per seed, 200 seeds, research forced, no predator. The metrics were fixed before the runs (D-053).
- **True breaking news.** It is absorbed within about 7–8 ticks, and volume roughly triples.
- **False breaking news.** The price follows it only as far as the ideal posterior does, since everyone discounts breaking news by q_false. The correction 20 ticks later is the most stressed moment of any scenario: the largest gap to p*_avail is 0.20–0.29, and arbitrage volume doubles.
- **Trend followers react but barely amplify.** They trade with every move (+3 to +46 shares; all but one CI above 0) and chase the correction's reversal. Yet overshoot rises by at most 0.007, and recovery is often 1–2 ticks *faster* with them. This holds at their configured size of 2 traders × 2 shares per tick.
- **Collateral depeg** (the main market's USDC at 0.90 for 30 ticks). The arbitrageur withdraws: the venue gap more than doubles (0.12 → 0.26) and its volume falls about 30%. Main-market accuracy is unchanged. Noise-trader withdrawal, a scenario input, lowers activity but not accuracy.
- **Batching after news.** Recovery doubles (6.9 ticks public, 13.5 ZK, 14.7 commit-reveal), and the price moves in 5-block steps: the cost side of the defense.

### 6.6 Manipulation (E5; descriptive; adversarial worst case; `phase3b/e5/`)
- **Setting.** A whale backs the wrong outcome: it holds the price of the outcome that will happen at 0.30 until its budget is spent. The scenario picks its side, as the forced-false shock does. This is a worst case, not a model of typical whales.
- **Manipulation verified:** its target lay on the wrong side of p*_avail in 94.5% of its window.
- **Cost and distortion grow with the budget.** Budgets of 50, 200 and 800 lose 39, 171 and 648 (about 80%). Extra deviation × duration is +2.8, +11.2 and +39.7 probability-ticks.
- **Informed researchers collect about 80% of its loss.** Trend followers lose by chasing it. The arbitrageur reduces the distortion only slightly.
- **The distortion outlasts the whale.** After a large whale stops, the price stays about 0.39 from p*_avail until the market ends.
  - Researchers already hold more than their Kelly targets (1.56×), so nobody has the capital or the reason to push it back: the limits of arbitrage.
  - This depends on the model's fixed bankrolls and quarter-Kelly sizing.

---

## 7. Synthesis
*(after review; see `synthesis.md`: "the dominant adversary is other informed agents"; "trust vs accuracy")*

## 8. Limitations and disclosures
*(after review; every D-entry that touches results, from `DISCLOSURES.md`)*

## 9. Conclusion and future work
*(after review)*

## Appendix A — Reproducibility
*(after review: environment set-up, commands per experiment, the commit and seed range of every archived run)*

## Appendix B — Decision log summary
*(after review)*
