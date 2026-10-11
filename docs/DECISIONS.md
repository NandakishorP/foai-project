# Design Decisions

Running log of agreed changes to `docs/SPEC.md`. Each entry: date, decision, reason. Newest at the bottom.

---

## D-001 — Truth lost is mean squared error with an additive decomposition
**Date:** 2026-10-10 · **SPEC:** §2, §7

**Decision.** Truth lost = `E[(p − p*_full)²]`, decomposed as
`E[(p − p*_full)²] = E[(p − p*_avail)²] + E[(p*_avail − p*_full)²]` (aggregation loss + participation loss).
Each term is reported as an RMS with 95% CIs; shares of truth lost are stated in MSE units. A pytest checks that the cross term `E[(p − p*_avail)(p*_avail − p*_full)]` averages to ≈ 0 across seeds.

**Reason.** The original absolute-error version (`Σ|p − p*_full|`) only satisfies the triangle inequality, so its "decomposition" did not add up. With squared error, the cross term vanishes in expectation. By the tower property, `E[p*_full | acquired info] = p*_avail`, and `p` depends only on acquired info plus randomness independent of `Y` and of the unacquired signals.

**Scope limits (written into SPEC).** The decomposition is an identity in expectation across seeds, not per run. It requires `Y ~ π` and signals drawn from the same model the ideal prices use as their likelihood. It does not hold in Polymarket real-data mode (`Y` fixed by history).

---

## D-002 — Identity binding in the `sealed_order` circuit
**Date:** 2026-10-10 · **SPEC:** §5

**Decision.** Traders register `id = Poseidon2(trader_secret)` in an on-chain registry with a registration stake; the registry keeps a Merkle root. The circuit adds public input `identity_root` and proves Merkle membership of the trader's `id`. The nullifier `Poseidon2(trader_secret, batch_id)` then means "one order per *registered identity* per batch".

**Reason.** Without binding, `trader_secret` is free to choose, so one trader could use several secrets and get several nullifiers. Sybil resistance comes only from the registration stake, and the report must state this.

**Implementation choice (Claude, pending owner confirmation).** Merkle membership was chosen over publishing the identity commitment directly. A public identity would let predators link each sealed order to an address's trading history and feed their "is informed" posterior, which partly undoes the defense. The cost is a larger circuit (a Merkle path in-circuit).

---

## D-003 — COMMIT_REVEAL baseline has escrow + slashing; ZK's claimed contribution narrowed
**Date:** 2026-10-10 · **SPEC:** §5, §5.1

**Decision.** The COMMIT_REVEAL baseline is the strongest non-ZK version, with escrow and slashing. SPEC §5 no longer claims ZK makes the free option impossible: slashing deters it in both modes. ZK's distinct contribution is that **every commitment is proven valid and solvent at commit time** (plus one-per-identity, without revealing identity). E3 must measure what that is worth under spam / invalid-order / free-option attackers.

**Reason.** Comparing ZK against a deliberately weak baseline would overstate its benefit, and the review will ask exactly this.

---

## D-004 — Batch clearing by netting through the LMSR
**Date:** 2026-10-10 · **SPEC:** §4

**Decision.** Opposing buy-YES / buy-NO orders offset as complete sets. Only the net imbalance `d` trades against the same LMSR used in other modes. Every filled order pays one uniform price `p` equal to the LMSR's average price for `d` (`p` = marginal price if `d = 0`). Orders whose limits are violated are dropped (escrow refunded) and the rest re-cleared until stable.

**Detail (Claude).** Dropped orders are never re-admitted in later rounds. This guarantees termination in ≤ (number of orders) rounds and is easy to explain. A re-admitting fixed-point search could fill slightly more orders but may cycle.

**Reason.** Keeping the same LMSR as the backstop means PUBLIC and ZK_BATCH differ only in how orders reach the market, not in liquidity depth. Otherwise E3 would confound the defense with a change of market maker.

---

## D-005 — Reference venue for arbitrageurs; parity arbitrage removed
**Date:** 2026-10-10 · **SPEC:** §4, §6

**Decision.** The reference venue is a second, smaller LMSR for the same event, with its own `b`, its own noise traders, and **public news only, with a delay**. Informed forecasters trade only the main venue; arbitrageurs close the gap between venues. YES+NO parity arbitrage is removed.

**Reason.** On a single LMSR, YES + NO prices sum to 1 by construction, so parity arbitrage has nothing to do. A reference venue driven by `p*_full` or `p*_avail` would inject truth into the market for free and contaminate every metric. Feeding it only delayed public news avoids that.

**Note for the report.** Both venues pay out on the same `Y`, so arbitrage is riskless at resolution. In effect, arbitrageurs pool the two venues' liquidity, and they pull the main price toward a public-information-only price in the short run. This is realistic cross-venue behaviour and part of what the model measures.

---

## D-006 — Pre-registered hypothesis criteria
**Date:** 2026-10-10 · **SPEC:** top, §7

**Decision.** Verdict criteria for H1 and H2 live in `docs/PREREGISTRATION.md` and are committed before E2a runs. H3's criteria are committed before E3. Any later change is logged here and disclosed in the report.

**Reason.** Fixing the thresholds before seeing data is the strongest defence against "you tuned it to come out true".

---

## D-007 — Phase 2 reordered: FastEngine science first, on-chain fidelity second
**Date:** 2026-10-10 · **SPEC:** §11

**Decision.** Phase 2 splits into **2a** (mempool, builder, predator, E2a + E2b, all on FastEngine) and **2b** (contracts + Foundry tests, EvmEngine on Anvil, differential test).

**Reason.** It gets the core scientific result (H1/H2) early and de-risks the schedule. The differential test in 2b still proves the FastEngine results transfer to real contracts.

---

## D-008 — Repository setup
**Date:** 2026-10-10

**Decision.** `spec.md` moved to `docs/SPEC.md`, `claude.md` renamed to `CLAUDE.md`, git initialised on `main`, `.gitignore` added (Python, Foundry, Noir build outputs, data caches).

**Reason.** Matches the layout in SPEC §10 and the commit-per-step rule in CLAUDE.md.

---

## D-009 — Foundry toolchain: do not overwrite the existing foundry-zksync install
**Date:** 2026-10-10

**Decision.** The installed `forge`/`cast` are foundry-zksync (`1.3.5-foundry-zksync-v0.1.7`), which the owner uses for another project. Do not run `foundryup` over it. How to get a stable `forge` for this project is still open (see Q4). Not needed until Phase 2b.

---

## D-010 — Python package lives in `sim/tfs/`
**Date:** 2026-10-10 · **SPEC:** §10

**Decision.** `pyproject.toml` sits at the repo root and uses `sim/` as the source root, so the package is `sim/tfs/` (`tfs/core`, `tfs/market`, `tfs/engines`, ...). YAML configs stay outside the package in `sim/experiments/configs/` (the path in CLAUDE.md). The CLI is `python -m tfs`.

**Reason.** SPEC §10 shows `sim/` holding the package's subfolders directly, but Python's import name must match a directory name. A standard source-root layout keeps `import tfs` working without import-path tricks.

---

## D-011 — Phase 1 Python dependencies
**Date:** 2026-10-10

**Decision.**
- Runtime: `numpy` (vectorised signal tapes, RNG), `scipy` (t-quantiles for 95% CIs), `pyyaml` (configs), `matplotlib` (static milestone and experiment plots).
- Dev: `pytest`, `hypothesis` (property tests for LMSR invariants).
- Not added yet: pandas (the csv module is enough so far); Plotly (deferred to the Phase 4 dashboard).
- Environment: `uv venv --python 3.12 .venv` and `uv pip install -e ".[dev]"`.

**Reason.** Keep dependencies minimal (CLAUDE.md); each one above is used for a concrete purpose.

---

## D-012 — FastEngine uses floating point; engine semantics
**Date:** 2026-10-10 · **SPEC:** §3.3, §4

**Decision.**
- FastEngine's LMSR uses Python floats with log-sum-exp, not a mirror of PRBMath fixed point. The tolerance for the FastEngine ↔ EvmEngine differential test is set in Phase 2b.
- Trades carry a limit on the *average* price and either fill completely or revert, like an on-chain slippage check.
- `Bundle` executes several trades all-or-nothing (used by arbitrageurs now, by builders and predators later).
- `Engine.submit(tx)` executes one transaction as its own block; `build_block(ordered_txs)` executes a block in exactly the given order, because ordering is decided by the builder.

**Reason.** Floats keep the Monte Carlo engine simple and fast. Fixed-point rounding matters only for the on-chain comparison, which the differential test covers. Fill-or-revert limits make slippage protection explicit; front-running in Phase 2 depends on it.

---

## D-013 — Two belief models behind one switch
**Date:** 2026-10-10 · **SPEC:** §6 · **Owner decision (Phase 1 planning)**

**Decision.** `agents.belief_model` selects how informed agents (forecasters and public-news traders) combine signals with the price:
- `own_signals` (SPEC default): log-odds = prior + every signal seen; the price is ignored.
- `price_anchored`: log-odds = logit(price) + r, where r is the agent's information not yet in the price. r grows with each new signal and shrinks by the log-odds impact of the agent's own fills, never changing sign.

Both run in E1. One is chosen by the pre-declared rule D-016, before any predator experiment.

**Reason.** Under `own_signals`, Kelly traders push the price toward a wealth-weighted *average* of beliefs, not the pooled posterior `p*_avail` (which sums independent private LLRs). The market could then structurally fail to aggregate private information, muting H2 for a modelling reason. `price_anchored` pools information, but it treats noise-trader moves as information. E1 measures which matters more instead of assuming.

---

## D-014 — Non-researching forecasters sit the market out
**Date:** 2026-10-10 · **SPEC:** §2.1 · **Owner decision**

**Decision.** A forecaster that does not research in a market does not trade in it at all.

**Reason.** It makes the research decision the participation decision: the clean Grossman–Stiglitz reading. Public news still reaches the main market via public-news traders (D-019) and arbitrage with the reference venue.

---

## D-015 — Fixed bankroll per market (changes SPEC §2.1 "carry wealth")
**Date:** 2026-10-10 · **SPEC:** §2.1 · **Owner decision**

**Decision.** Every forecaster bets from the same bankroll in every market. Profits and losses accumulate in a separate ledger (per-market PnL records). What carries across a season is the learned EMA estimate of research profit, not wealth.

**Reason.** With compounding wealth, trading profit scales with wealth while research cost is fixed in dollars. Winners' research would grow more profitable over the season, so participation could drift upward even without predators. That would confound the "stable without predators" milestone and H2.

---

## D-016 — Belief-model selection rule for E1 (pre-declared)
**Date:** 2026-10-10 · **Fixed in the approved Phase 1 plan before any simulation was run.**

**Rule.** Run E1 under both belief models. Choose the model with the lower aggregation-loss RMS at the base configuration. If the two 95% CIs overlap, keep `own_signals` (the spec default). The chosen model is used for cost calibration, the season baseline, and all Phase 2 experiments. The full E1 sweep is reported for both models regardless.

**Disclosure.** A 40-seed smoke run of the base config under both models was made while debugging the simulation loop (before E1). Its numbers do not enter any result.

---

## D-017 — Research-cost calibration rule (pre-declared)
**Date:** 2026-10-10 · **Fixed in the approved Phase 1 plan before any simulation was run.**

**Rule.** Run the base configuration with the chosen belief model, `research.mode: always`, a single market and 200 seeds, with no predators. Set `cost_median` to the median gross trading profit of a researching forecaster across all (forecaster, seed) pairs. Costs are lognormal around it (`cost_log_sigma` = 0.5). The value is written into the season configs with this rule cited, and is not changed afterwards to influence any result.

**Reason.** Costs must sit where some forecasters find research worthwhile and some do not, so that movement in participation in either direction is visible. The rule fixes the scale before predators exist, so it cannot be tuned toward H2.

---

## D-018 — False news deferred
**Date:** 2026-10-10

**Decision.** Phase 1 implements only true shocks (high-precision public signals). False news waits for an answer to Q1, because a false-news process unknown to the ideal prices would break the MSE decomposition (D-001).

---

## D-019 — Public-news traders on both venues
**Date:** 2026-10-10 · **SPEC:** §6

**Decision.** One `PublicNewsTrader` per venue (configurable) trades on public news only, after a delay: 1 tick on the main market, 5 on the reference venue. It uses the same belief model as the forecasters.

**Reason.** The reference venue must "receive public news with a delay" (D-005), so some agent has to trade it on that news. On the main market, under `price_anchored`, someone must carry public news into the price, since forecasters add only private information there. The same agents exist under both belief models, so E1 compares like with like.

---

## D-020 — Research decision details
**Date:** 2026-10-10 · **SPEC:** §2.1

**Decision.**
- A forecaster with no research experience researches (optimistic initialisation). In a season's first market everyone researches, which is the fixed participation H1 assumes.
- The EMA of gross trading profit updates only in markets where the forecaster researched.
- ε-exploration only adds research: a forecaster whose rule says "no" researches anyway with probability ε. The exploration coin is drawn every market from its own stream, so decisions do not shift other random draws.

---

## D-021 — Execution rule for Kelly traders (Phase 1 "simple execution")
**Date:** 2026-10-10 · **SPEC:** §6

**Decision.** Informed agents send at most one order per tick and never make a trade with negative expected value under their own belief. They trade only in the direction belief − price points, up to the fractional-Kelly target exposure. Each order is capped so it cannot push the price past the belief (LMSR closed form), and its limit price equals the belief. Exposure is increased by selling the opposite side first, if held.

**Reason.** Explainable, and it avoids churn: an agent never sells into a price it considers unfavourable. Under `price_anchored`, the same rule means the agent never unwinds a position merely because its information is now priced in. The limit at the belief matters in Phase 2: being front-run can at worst cancel an order, never fill it at a price the agent thinks is bad.

---

## D-022 — Outcomes of the pre-declared Phase 1 rules
**Date:** 2026-10-10

- **D-016 applied (E1, 200 seeds):** aggregation-loss RMS at the base config is 0.178 [0.162, 0.192] under `own_signals` and 0.245 [0.236, 0.254] under `price_anchored`. The CIs are disjoint, so **`own_signals` is selected**. This is provisional pending Q5 below.
- **D-017 applied:** median gross profit of a researching forecaster = 5.4486 (n = 2000; 73% of values positive). `cost_median: 5.45` in `season_baseline.yaml`.

---

## D-023 — Metric additions after E1
**Date:** 2026-10-10

**Decision.**
- New per-market column `public_only_mse` = E[(p_public − p*_avail)²], the gap of a price that ignores all research. New summary value `research_captured` = 1 − aggregation MSE / public_only MSE (ratio of means across seeds; no CI yet).
- New per-market indicator `settled_k` (did the price settle within ε of p*_avail after shock k?). Charts show the settled share with a CI instead of mean time-to-ε, because mean time-to-ε over uncensored runs only was misleading when 60–100% of runs were censored. Time-to-ε stays in the CSVs.

**Reason.** E1 showed the price stays close to the public-only posterior. Without a benchmark, "aggregation loss 0.03" could not be interpreted.

---

## Phase 1 finding F-001 — the market aggregates little private information
**Date:** 2026-10-10 · **Status: needs an owner decision (Q5)**

- Under `own_signals` at the base config with full participation, the main price captures about **9%** of the information research adds beyond public news (`research_captured` = 0.088). The price sits within RMS ≈ 0.05 of the public-only posterior. Under `price_anchored` it is −0.74 (worse than ignoring research).
- Diagnosis (100 seeds per variant, not a tuning exercise): removing the arbitrageur, or both the arbitrageur and the main-venue public trader, changes little. A 10× forecaster bankroll changes little under `own_signals`.
- Cause: each forecaster's belief is dominated by shared public news (about 2 nats) against its own private signals (about 0.2 nats), and Kelly traders move the price toward the *average* belief. `p*_avail` *sums* the independent private log-likelihood ratios, so the market reflects roughly one forecaster's worth of private information. This is the averaging risk identified in Phase 1 planning.
- Consequences: the milestone "price converges to p*_avail" is **not met**. Time-to-ε after the shock settles in only ~11% of base runs. More forecasters *increase* truth lost (more information exists, little more is priced).

---

## D-024 — Correlated research signals become the default model
**Date:** 2026-10-10 · **SPEC:** §2 · **Owner decision (answer to Q5)**

**Decision.** At each research event every potential forecaster i receives s_i = ±mu + u + e_i, with a common component u ~ N(0, tau²) and idiosyncratic noise e_i ~ N(0, sigma_e²). The parameter rho = tau²/(tau² + sigma_e²) is the correlation of two forecasters' signals given Y. rho = 0 is independent research (the F-001 setting); rho = 1 is the textbook Grossman–Stiglitz shared signal.

p*_avail and p*_full use the exact Gaussian posterior for a group of k researchers, LLR = 2·mu·Σs_i/(k·tau² + sigma_e²) (Sherman–Morrison; the group mean is sufficient). They do not sum individual LLRs. Tests check this against a brute-force multivariate Gaussian, by Monte Carlo calibration at rho = 0 and 0.6, with a negative control showing naive summation is overconfident, and with a zero cross term at rho = 0.6.

**Reason.** F-001: with independent signals the Kelly market prices the average belief, so research participation barely moves market accuracy. The independent-signal results are kept as an E1 finding (`docs/report/findings/F-001_independent_signals/`).

---

## D-025 — Consequences of the correlated model
**Date:** 2026-10-10 · **SPEC:** §2, §2.1

**Decision (Claude; approved by the owner 2026-10-10).**
1. **Equal research quality for all forecasters.** At rho = 1 every forecaster must see the identical signal, which per-forecaster precisions cannot allow. Heterogeneity (SPEC §2.1) now comes from research costs only.
2. **`pooled_nats` replaces per-forecaster nats.** The configured quantity is the information of *all* forecasters' research combined (2 nats, the same total as before), and tau², sigma_e² are derived from it and rho. Sweeping rho then changes how the same information is spread across forecasters, not how much exists. At rho = 0 each forecaster holds pooled_nats/N = 0.2 nats, the old mean.
3. **Research events are shared in time.** They are a single Poisson stream, rather than independent arrival times per forecaster. Within one event the common component must hit everyone at once. At rho = 0 this reproduces F-001's information content but synchronises arrival times; the E1 rho = 0 point is compared against F-001 to check the difference is small.
4. **CRN preserved:** event times and u come from shared streams, and each forecaster's e_i from its own stream.

---

## D-026 — Baseline calibration rule (pre-declared, before any calibration run)
**Date:** 2026-10-10 · **Owner requirement:** without predators, (a) share of research information priced ≥ 0.6 and (b) steady-state participation 50–70%. This is calibration of the no-predator baseline, not outcome tuning. It runs before any predator code exists, and the values are frozen and committed before any Phase 2a experiment.

**Rule.**
- Fixed: `belief_model: own_signals` (D-016), `cost_log_sigma: 0.5`, every other base parameter. Calibrated: `information.private.rho` and `research.cost_median`.
- Grid: rho ∈ {0, 0.25, 0.5, 0.75, 0.9, 1.0}.
  - For each rho, compute the cost unit M(rho) by the D-017 procedure: the median gross profit of a researching forecaster at full participation, single markets, 200 seeds.
  - Candidate cost medians: m·M(rho) for m ∈ {0.25, 0.5, 0.75, 1.0}.
- Each grid point runs a 30-market season, 200 seeds, endogenous research, no predators. The steady state is markets 21–30.
  - (a) `research_captured` = 1 − mean aggregation MSE / mean public-only MSE, over steady-state markets and seeds.
  - (b) mean participation over steady-state markets and seeds.
- Selection:
  - Choose the **smallest feasible rho** (information as dispersed as possible, closest to the F-001 model). For that rho, choose the m whose participation is closest to 60%.
  - If no grid m of that rho has participation in [50%, 70%] but (a) holds and participation brackets the band between adjacent m values, bisect m (at most 6 steps) until participation lands in the band, then re-check (a).
  - If no rho is feasible: stop and report to the owner; nothing is frozen.
- The whole grid is saved (`results/baseline_calibration/grid.csv`) and reported, not only the chosen point.

---

## D-027 — `price_anchored` double-counts correlated information
**Date:** 2026-10-10 · **Owner check (point 3)**

**Finding.**
- *Own evidence is counted once.* A lone anchored trader moves the price's log-odds by exactly the sum of its evidence, with no further pushing on later ticks, and carries only the unpriced remainder when its orders are capped (tests/test_anchored_counting.py). Tracking "evidence not yet pushed by my own fills" generalises "evidence since my last trade" to trades that only partly push.
- *Correlated evidence is double-counted across agents.* Two anchored agents given the same signal (LLR 0.8) push the price's log-odds to 1.6. Each assumes the price holds only others' independent information. So `price_anchored` is not a valid model for rho > 0.

**Decision.** The new E1 sweeps rho under `own_signals` only. The belief-model comparison stays in F-001 (rho = 0, where the anchored model is valid).

---

## D-028 — Baseline calibration round 1 (D-026): no feasible point, nothing frozen
**Date:** 2026-10-10 · Rule committed at `64b802d` before the run. Full grid in `docs/report/calibration/D-026_round1/`.

**Result.** None of the 24 grid points meets both (a) research_captured ≥ 0.6 and (b) steady-state participation 50–70%. The closest is rho = 1.0 with cost = 0.25·M: participation 61% ✓, captured 0.47 ✗. Captured rises with rho at every cost level. Steady-state participation never exceeds 61%.

**Diagnostic (one variant at a time, nothing selected).**
- At rho = 1 with *full* participation, captured is 0.87. The shortfall is informed capital at ~6 researchers, not the model's ability to aggregate.
- Raising forecaster capital (bankroll ×4, or Kelly k = 1) gives 0.98. Removing the arbitrageur, the ref-venue public trader or the noise traders, or zero latency, changes little.

**Measurement caveat.** `research_captured` is ill-conditioned when little research information exists: low rho at low participation makes the denominator small. The strongly negative values there (down to −2.4) mean "the price is noisier than the small research signal". They do not mean the market is worse than at full participation in absolute terms.

**Status.** Rule D-026 says stop and report to the owner. Pending: whether to extend the calibrated set (e.g. informed capital), relax a criterion, or change the steady-state definition. Until then `rho` stays at the placeholder 0.0 in base.yaml, and E1, the season baseline and the pre-registration rewrite wait.

---

## D-029 — Baseline calibration round 2 rule (pre-registered before any run; owner answer to Q6)
**Date:** 2026-10-10 · Replaces the grid and selection parts of D-026. Criteria (a), (b), the steady state (markets 21–30), 200 seeds, `own_signals`, `cost_log_sigma` 0.5 and every other base parameter stay as in D-026.

**Informed capital.** Parameterised as `capital_ratio` = forecaster bankroll / b_main (LMSR depth), replacing the absolute bankroll. Bankroll = capital_ratio × b_main, fixed per market (D-015). Quarter-Kelly is kept. (Consequence: in the E1 b sweep, forecaster capital now scales with b.)

**Metric (b of the owner's conditions).** "Share of research information priced" = 1 − Σ aggregation MSE / Σ public-only MSE, pooled across all runs (ratio of sums, never a mean of per-run ratios). Its numerator and denominator are always reported alongside it (`research_captured_num`, `research_captured_den` in summaries; `share_num`, `share_den` in the grid). The round-1 code already pooled; round-1 values are unchanged. What was missing was reporting the parts.

**Grid.**
- rho ∈ {0, 0.25, 0.5, 0.75, 0.9, 1.0} × capital_ratio ∈ {1, 2, 4} (bankrolls 100, 200, 400 at b = 100) × cost multiplier m ∈ {0.25, 0.5, 0.75, 1.0}: 72 seasons.
- The cost unit M is recomputed for each (rho, capital_ratio) by the D-017 procedure, since profits scale with capital.

**Selection.**
1. Feasible = share priced ≥ 0.6 **and** steady-state participation in [50%, 70%].
2. Among feasible points: smallest rho, then smallest capital_ratio, then participation closest to 60%.
3. **Fallback, if nothing is feasible:** among points with participation in [50%, 70%], take the highest share priced. Freeze it, record it as a limitation, and proceed without returning to the owner.
4. D-026's bisection step is dropped: the fallback now covers the no-feasible case, and a grid-only rule is simpler to audit.

The whole grid is archived and reported. The selection code is `tfs/experiments/baseline_calibration.py`; the rule is unit-tested on hand-made grids (`tests/test_baseline_calibration.py`).

---

## D-030 — Baseline calibration round 2 result: FROZEN
**Date:** 2026-10-10 · Rule D-029 committed at `8087302` before the run. Full 72-point grid with numerators and denominators: `docs/report/calibration/D-029_round2/grid.csv`.

**Chosen (feasible, preference order D-029 (c)):** rho = **1.0**, capital_ratio = **2.0** (bankroll 200 at b = 100), cost multiplier 0.25 × cost unit 6.864 → cost_median = **1.716**.
- Steady-state participation 55.2%; share priced 0.703 (numerator 0.00927 / denominator 0.03121).
- Only 2 of 72 points are feasible, both at rho = 1. The other is capital 4 (participation 51.4%, share 0.82); the preference for smaller capital picks capital 2.
- No point with rho < 1 meets both criteria. At rho ≤ 0.9, steady-state participation stays ≤ 50% at every capital level and cost on the grid. The best rho = 0.9 points reach a share of 0.77, but at 31% participation.

**Frozen in:** `base.yaml` (rho, capital_ratio) and `season_baseline.yaml` (cost_median). These values are not changed for any Phase 2 experiment.

**Interpretation for the report.**
- At rho = 1 every researcher sees the same research signal. Any single researcher makes p*_avail = p*_full, so participation loss is zero whenever at least one forecaster researches.
- Researcher exit then mainly removes **informed capital** pushing the price toward p*_avail: the Grossman–Stiglitz channel. It shows up as aggregation loss, not participation loss. This is why H2 is judged on total truth lost (PREREGISTRATION).
- The calibration needed rho = 1 and cheap research (a quarter of the typical gross profit) to keep participation at 50–70%. That limitation is stated in the report.

---

## D-031 — Project-local stable Foundry (answer to Q4)
**Date:** 2026-10-10

**Decision.**
- Stable Foundry **v1.4.4** (the same version as the stable `anvil` already on this machine) is installed into `.tools/foundry/bin` (gitignored) by `scripts/install_foundry.sh`.
- The script downloads and unpacks the official release tarball only. It does not run `foundryup`, write to `~/.foundry` or edit shell profiles. The `Makefile` points `FORGE`/`ANVIL`/`CAST` at `.tools/foundry/bin`; `make foundry-version` shows them.
- Verified: a fingerprint of `~/.foundry` (SHA-256 of `bin/`, `versions/`, `share/`, `keystores/`; path, size and mtime of every file in `anvil/` and `cache/`) plus `~/.zshrc`, `~/.zprofile` and `~/.profile` is identical before and after the install (36,397 entries). Global `forge` is still `1.3.5-foundry-zksync-v0.1.7`.

**Reason.** The owner uses foundry-zksync globally for another project.

---

## D-032 — Phase 1 milestone (recalibrated) and binding pre-registration
**Date:** 2026-10-10 · Outputs: `docs/report/phase1_milestone/` (generated at clean commit `1d3cb67`).

**E1 (single markets, full participation, 200 seeds, own_signals).** Baseline truth-lost RMS 0.035 [0.034, 0.036]; share priced 0.96 (num 0.0012 / den 0.0327); 90% of runs settle within ε after the shock.
- rho sweep, from 0 to 1: truth-lost RMS 0.171 → 0.128 → 0.095 → 0.065 → 0.048 → 0.035; share 0.17 → 0.96.
- At rho = 0 and capital_ratio 1, the F-001 result is reproduced (truth-lost RMS 0.177 vs 0.178; share 0.11 vs 0.09). Synchronised research events (D-025) change little.

**Season baseline (30 markets, 200 seeds).**
- Participation: 100% (market 1) → 82% (market 2) → 60% (markets 11–20) → 55% [52%, 59%] (markets 21–30).
- It is still drifting slowly down in the final stretch (56% at market 21, 53% at market 30). This is reported as observed; it was not adjusted.
- Steady-state truth-lost MSE 0.0100, of which aggregation 0.0093 and participation 0.0007. The season-wide cross term is 2.0e-5 [−6.5e-5, 1.1e-4], consistent with 0.

**Pre-registration.** `docs/PREREGISTRATION.md` rewritten and made binding. H1/H2 are judged on total truth-lost RMS, the leakage ratio (H1) and the participation gap (H2), using strict CI rules and paired bootstrap CIs. The aggregation/participation split is descriptive only.
- Choices made by Claude where the owner gave no number: H2's "rises sharply" threshold (+30%), H2's contradiction rule, and the leakage ratio as the share of informed edge *lost*. These are flagged for the owner and can be amended before any E2 run.

---

## D-033 — Phase 2a design and owner amendments (before any E2 run)
**Date:** 2026-10-10 · Phase 2a plan approved with four amendments.

**Design.**
- A mempool stamps each transaction with an arrival time in the block.
  - PUBLIC visibility: an observer with latency ℓ sees a pending transaction iff arrival + ℓ < 1.
  - Arrival times are rank-based on the same seeded permutation the Phase 1 builder used. With no predators the block order is unchanged.
- A fee-ordered builder places predator front-runs (and optional back-runs) immediately around their victim; one bundle per victim, highest bid wins.
  - Placement is **not atomic** with the victim (priority-gas-auction style). A front-run can fill while its victim later reverts, at the predator's risk.
  - This is a simplification of the plan's "Flashbots bundle" wording, made so the victim's transaction is never held hostage to the predator's bundle.
- An MEV predator agent keeps a per-address Beta posterior and an EV-maximising front-run size.
- Statistics: paired bootstrap; verdict code follows PREREGISTRATION exactly.

**Owner amendments.**
1. **Markouts start at the post-trade price** (after the victim's execution) and run to the price H ticks later, measured in log-odds. The predator's own trades inside a window are subtracted exactly: LMSR log-odds impacts are additive. It also unwinds at H+1, outside the window. Test: noise traders' posterior mean stays near the prior while an informed trader's rises.
2. **EV is net of the exit.** The LMSR slippage of the unwind (hold) or back-run (sandwich) is in the EV. Property test: EV equals realised PnL in a deterministic no-news scenario.
3. **`base_fee = 0`** in the reference configuration, so the 0-predator twin matches D-030 and Phase 1 exactly. The fee stays as a config option only. Regression: a digest of prices, PnL and researchers for 3 seeds × 4 markets of the season baseline, taken at `b803d95` before any Phase 2a code (`d99b9b2c…`), must be reproduced with zero predators.
4. **E2a uses 30-market seasons with research forced on.** H1 is scored on markets 6–30 after a 5-market warm-up. Predator beliefs persist across markets in E2a and E2b. PREREGISTRATION amended accordingly.

The remaining predator parameters (markout threshold, H, drift-EMA decay, warm-up length, latency, bid share, capital) are fixed with rationale in the commit that adds the predator (PREREGISTRATION rule 5).

---

## D-034 — Predator agent and its reference parameters (fixed before any E2 run; PREREGISTRATION rule 5)
**Date:** 2026-10-10 · Code: `sim/tfs/agents/predator.py`. Values and per-line rationale: `base.yaml` → `agents.predators`. E2a/E2b use them with `count: 1` as the reference.

**Reference parameters.**

| Parameter | Value | Rationale |
|---|---|---|
| latency | 0.2 | Reads a pending transaction if it arrives in the first 80% of the block interval. Middle of the E2a sweep {0.05, 0.2, 0.5}. |
| capital_ratio | 2.0 | As well funded as one informed forecaster (D-030). |
| horizon H | 10 ticks | Researchers push the shared signal in over several ticks; public news arrives about every 20 ticks. 10 ticks capture order-flow continuation and stay shorter than the gap between news items. |
| markout_threshold | 0.0 | "The price kept moving my way at all". Noise trades succeed about half the time, which equals the Beta(1, 1) prior mean, so P(informed) = 2θ − 1. |
| drift_ema_alpha | 0.1 | E[drift \| informed] averages the last ~10 informed markouts. |
| bid_share | 0.5 | Half the expected gross profit goes to the builder. |
| min_profit | 0.01 | One cent. |
| slippage | 0.01 | Same scale as the arbitrageur's. |
| own_impact_reversion | 1.0 | See below. |
| back_run | false | Reference predator holds to ride informed drift (SPEC §6: back-running optional). The sandwich variant is reported. |
| warm-up | 5 markets | Already in PREREGISTRATION: H1 scored on markets 6–30. With ~500–900 executed trades per market across ~23 addresses, each active forecaster contributes dozens of markouts per market, so after 5 markets each posterior rests on ≳ 75 observations (sd of θ ≲ 0.06). |

**Design changes found while debugging (one seed, 6–8 markets, research forced on; functional checks only, no paired comparison, no E2 run).**
1. **Revert protection.** The predator's own transactions are dropped, and pay no tip, if they would revert, as searchers' bundles are (`Trade.revert_protected`). Without it, failed front-runs still paid their bids and the predator bled its whole bankroll.
2. **Slot pricing.** The predator prices its front-run at the victim's slot. It replays the visible transactions ordered ahead of the victim; each moves the price only if its own limit allows. With rho = 1 all researchers trade the same way in the same block, so the block-start price was stale: front-runs reverted on their limits, or pushed victims past theirs. After the fix, no victim reverted in the checks.
3. **`own_impact_reversion` (new parameter, r = 1).** The hold-variant EV first assumed the predator's own front-run impact persists until it unwinds. In an LMSR the round trip then looks increasingly profitable with size (convexity), and the predator round-tripped thousands of shares at a loss. Its own trade carries no information, so informed traders, the public-news trader and the arbitrageur push it back within H ticks. The reference predator therefore expects to exit with its own impact undone, keeping the victim's impact and the informed drift. The sandwich variant needs no such assumption.
4. **No positions it cannot unwind:** no new front-runs once fewer than H + 2 ticks remain in the market.

**Tests (owner amendments).** Noise traders' posterior stays at the prior mean (|θ − 0.5| < 0.08) while the informed trader's rises (θ > 0.7). The predator's own trades inside a markout window are subtracted. EV equals realised PnL exactly in three deterministic no-news cases: sandwich; hold in a frozen market with r = 0; hold with r = 1 where another agent undoes the predator's impact. Also tested: front-runs never make the victim revert (property test); no trade when costs exceed EV; slot replay.

---

## D-035 — E2a first attempt crashed (no results); overflow fix
**Date:** 2026-10-10

The first E2a run crashed after ~11 minutes with `OverflowError` in `cost_at_price`, called from the predator's affordability search. When the predator's side was nearly free (price near 0 or 1), the search bound ran to millions of shares and `expm1(shares/b)` overflowed. **No results were written**; the run produced no data that anyone looked at.

**Fix.** `cost_at_price` uses log-sum-exp for large trades, and handles certain or impossible sides exactly. Property tests: it never overflows, and it matches the q-based cost function. The predator's search is capped at 20 log-odds of price movement. The zero-predator digest is unchanged. E2a and E2b were then run from a clean commit with no other change.

---

## D-036 — Phase 2a results: H1 partly supported, H2 contradicted
**Date:** 2026-10-10 · Runs from clean commit `65eef4f` (`meta.json`: dirty false). Archive: `docs/report/phase2a/`. Per-run CSVs (31–38 MB) are not committed; `python -m tfs run sim/experiments/configs/e2a.yaml` / `e2b.yaml` at that commit regenerates them exactly.

**H1 (E2a, reference predator, markets 6–30, 200 paired seeds): PARTLY SUPPORTED.**
- Δ1 truth-lost RMS = +3.4% [+3.2%, +3.7%]: entirely ≤ +15% ✓.
- Leakage L = 0.130 [0.123, 0.138]: not ≥ 0.30 ✗.
- Front-running barely hurts accuracy in the short run (as H1 says), but it redistributes less of the informed edge than H1's threshold. The reference predator nets ~5.8 per market; informed PnL falls from 59.3 to 51.6 per market.
- Sweep:
  - 2 and 4 hold-predators: L = 0.16 / 0.19, Δ1 = +4.1% / +4.4%.
  - Latency matters little.
  - The sandwich variant (back_run): L ≈ 0.28, Δ1 ≈ −0.1%; predator nets ~74 and the builder ~76 per market. Several identical sandwichers behave like one, because ties go to the same agent.

**H2 (E2b, reference predator, markets 21–30): CONTRADICTED.**
- Participation gap G = 6.0 pp [4.5, 7.6]: entirely < 10 pp → contradicted by rule. Steady-state participation is 55.2% without predators and 49.2% with one.
- Δ2 truth-lost RMS = +11.1% [+6.2%, +17.0%], about 3× the short-run effect: the long-run channel exists and points the way H2 predicts.
- Sweep: 2 / 4 predators give G = 8.3 / 9.7 pp and Δ2 = +15% / +17%. Cost ×0.5 / ×2 change little.

**Interpretation (for the report; not a re-test).**
- The long-run (participation) channel is real and larger than the short-run channel, but an order of magnitude smaller than the "collapse" H2 posits, at these predator settings.
- One visible reason, in the replay: with a shared research signal (rho = 1), researchers trade the same way in the same block and mostly crowd each other out. Six of ten researchers revert on their own limits in the replayed block. That competition, not the predator, bounds research profits.
- These verdicts are final under the pre-registration. Any follow-up (e.g. more aggressive predators, other rho) is exploratory and must be labelled as such.

---

## D-037 — Owner ratification after Phase 2a
**Date:** 2026-10-10

1. **Verdicts stand as pre-registered**: H1 partly supported, H2 contradicted. They are not re-run or re-analysed to change them.
2. **Ratified:** the D-032 thresholds (H2 "sharp" > +30%, the H2 contradiction rule, leakage = share of edge lost) and the D-034 predator fixes. Both are disclosed in the report (`docs/report/DISCLOSURES.md`).
3. **Note for the report on `own_impact_reversion` (owner's note, with Claude's correction, agreed for the write-up).**
   - LMSR cost is path-independent: buying x and selling x with nothing in between costs exactly zero. So the predator's own impact always comes back out *through its own exit*.
   - In the EV formula this is the r = 0 case: if no one else reacts, the predator's exit removes its own impact and the round trip is neutral (the sandwich gain from the victim remains).
   - r = 1 assumes *other* traders also push the impact back before the exit. The exit then moves the price a second time, so the predator pays for its own impact twice (a loss of about x²/b).
   - r = 1 is therefore the pessimistic assumption about other traders' reaction, not a consequence of path independence. The debugging observation in D-034 (an r = 0 predator round-tripping thousands of shares at a loss) shows other traders do push back in this market. Exploratory run X-1 measures how much predator strength depends on r.

---

## D-038 — Phase 3 design note: E3 as a 2×2 (to be pre-registered at Phase 3 start)
**Date:** 2026-10-10 · Owner decision.

E3's core comparison is a 2×2: {predators 0, 1} × {PUBLIC, ZK_BATCH}. It separates the anti-predator effect of batching (the predator × policy interaction) from its anti-crowding effect: batching also stops researchers with a shared signal from crowding each other out within a block (F-002), with or without predators. The batch interval K, the costs of §5.1 and the other baselines (PRIVATE_RELAY, COMMIT_REVEAL) come on top. Exact criteria for H3 are pre-registered at Phase 3 start.

---

## D-039 — Exploratory robustness set X-1..X-3 (declared before running; EXPLORATORY)
**Date:** 2026-10-10 · Owner request. Configs: `sim/experiments/configs/exploratory/`. Outputs: `docs/report/exploratory/`. Reference setting, 200 paired seeds, the same paired statistics. **No verdicts: nothing here alters H1/H2.**
- **X-1** `own_impact_reversion` ∈ {0, 0.5}, alongside the reference 1, at the E2a and E2b settings.
- **X-2** E2b with 60-market seasons. Paired participation gap and Δ truth lost in windows 21–30, 31–40, 41–50, 51–60.
- **X-3** Staggered research arrival: each researcher receives each research event 0–3 ticks after emission (`information.private.max_delay: 3`; delay drawn per event and researcher from its own stream). Ideal prices keep emission times, so the decomposition still holds (test added). Run at the E2a and E2b settings, with max_delay 0 in the same run for comparison.
- **New crowding metric** for F-002: `forecaster_revert_share` = share of researchers' trades that revert.
- **Analysis code** now supports windows and exploratory runs without verdicts. Re-analysing the saved E2a/E2b runs with the new code reproduces both archived verdicts with identical statistics.

---

## D-040 — Exploratory results X-1..X-3 and finding F-002 (EXPLORATORY; verdicts unchanged)
**Date:** 2026-10-10 · `docs/report/exploratory/README.md`, `docs/report/findings/F-002_rent_dissipation/README.md`. Runs at `f98a78e`, clean.

- **X-1:**
  - r = 0 gives a self-destroying predator (−178 per market; informed traders gain; in E2b participation rises to 89%).
  - r = 0.5 gives a viable, more aggressive predator: E2b G = 10.4 pp [8.8, 12.1], Δ = +18% [+14, +24].
  - **H2's rule outcome is sensitive to predator aggressiveness.** At r = 0.5 it would read "partly supported", not "contradicted". The pre-registered verdict stands; this sensitivity is disclosed (DISCLOSURES.md).
- **X-2:** the gap does not widen over 60 markets (6.0 → 5.3 → 5.1 → 4.7 pp).
- **X-3:** researcher crowding is robust to staggered arrival (50% of researcher trades revert vs 56%). Predators gain slightly (E2b G = 8.4 pp).
- **F-002 written:** competition among identically informed researchers dissipates research rents (Holden & Subrahmanyam 1992, verified on RePEc). Predators tax a small pie.

---

## D-041 — Phase 2b toolchain and Solidity dependencies
**Date:** 2026-10-10 · Phase 2b plan approved.

- The Foundry project lives in `contracts/` (`contracts/foundry.toml`), matching SPEC §10's "contracts/ — Foundry project". The plan said a root `foundry.toml`; `contracts/` is cleaner.
- Built with the project-local forge v1.4.4 (D-031), Solidity **0.8.26** (pinned), optimizer 200 runs.
- Dependencies as git submodules (`forge install`), pinned by tag:
  - OpenZeppelin Contracts **v5.1.0** (ERC20, ERC1155 + Supply, SafeERC20);
  - PRBMath **v4.1.0** (SD59x18 `exp`/`ln` for the LMSR);
  - forge-std **v1.9.4** (tests).
- The Python side adds `web3` in an optional extra `[evm]` (EvmEngine only); logged when added.

---

## D-042 — EvmEngine conventions
**Date:** 2026-10-10

- **Python dependency:** `web3` 7.x in the optional extra `[evm]`. The Monte Carlo core does not need it.
- **Anvil** (project-local, D-031) is started per engine on a free port, with `--no-mining --order fifo --gas-price 0 --base-fee 0 --gas-limit 1e9`. FIFO plus manual `evm_mine` makes each block's order exactly the builder's send order; `test_block_order_is_the_builder_order` checks it.
- **Accounts:** each agent gets its own dev account; the deployer, builder and oracle proposer get their own.
- **Contracts are deployed from Python** (`contracts/out` artifacts). The planned `Deploy.s.sol` is not needed: deploying from Python keeps one source of the deployment order.
- **Unit conversion:** amounts in 6 decimals. Buys round to nearest; sells round toward zero (never one unit more than held). Limits in 18 decimals, rounded down.
- **Resolution** uses the optimistic oracle's undisputed path (propose → window → settle), then every agent redeems.
- `LMSRMarket.Traded` now carries the post-trade price, so per-trade before/after prices (used by anchored beliefs and predator markouts) can be rebuilt from logs.

---

## D-043 — Differential-test tolerance (stated before the test was written)
**Date:** 2026-10-10

The identical ordered blocks are replayed on FastEngine (floats) and EvmEngine (fixed point on-chain). After every block:
- every venue price: |Δ| ≤ 1e-6;
- every account's cash: |Δ| ≤ 1e-4 USDC (6-decimal rounding accumulates over hundreds of trades; one trade differs by ≤ 1e-6);
- every account's shares: |Δ| ≤ 1e-5;
- receipt ok flags: equal, except a **boundary case**, where a trade's FastEngine average price lies within 1e-6 of its limit. Boundary cases are counted and reported, never hidden; if one occurs, the engines' states may legitimately diverge from that block on, and the test reports that rather than loosening tolerances.

After resolution: payouts per account (|Δ| ≤ 1e-4) and market-maker PnL per venue (|Δ| ≤ 1e-4).

**Amendment (same day, after the first differential run; disclosed).**
1. **MM PnL tolerance.** The market maker's PnL collects the rounding of *every* trade, and each rounds by at most one 6-decimal unit in its favour, whereas an account sees only its own trades. The tolerance is therefore n_trades × 1e-6 (at least 1e-4). The first no-predator run showed 2.3e-4 over 988 trades: within the derived bound, but outside the original fixed 1e-4. That 1e-4 had been mis-specified, not exceeded by an error.
2. **Quantized replay.** Both engines now receive the same orders quantized to the chain's 6-decimal grid (amounts and fees; sells toward zero). In the first predator-market run the chain rounded amounts that FastEngine did not. That moved prices by about 1e-9 per trade, and because the predator deliberately pushes victims to exactly their limits, victims flipped from block 13 on and the states diverged (81 mismatches, 20 boundary cases). The no-predator market and the fuzz scenario passed without quantization. Quantizing the shared input removes a difference in *inputs*, not in market behaviour, so no tolerance is loosened.
3. **Pinned boundary decisions.** Even with quantized input, the predator market diverged at block 10. The predator sized a front-run so its victim's average price landed *on* the victim's limit. FastEngine compares average prices to ~1e-9 and rejected the trade by ~1e-9; the chain compares cash in whole 6-decimal units and accepted it. Predators create such boundary decisions on purpose at every front-run, so they are inherent and not a bug. The harness now handles any trade whose average price is within 1e-6 of its limit as follows: FastEngine decides, the chain's copy gets a limit forcing the same decision, and the case is **counted and listed** in the report. Every other trade must agree exactly, so a fill/revert mismatch away from a limit still fails the test. Prices, cash, shares, payouts and MM PnL are then compared at full strictness.
4. **Sealed-batch tolerance for fills (Phase 3a; disclosed, set after the first batch run).** The chain floors pro-rata margin fills to whole units and finds the imbalance by integer bisection. Batch states therefore drift apart in price by ~1e-8, within the 1e-6 price tolerance. A margin fill inverts the average-price curve, so it amplifies a state price difference Δp by about 2b/(p(1−p)) (about 1,000×).
   - The first market run showed 1.8e-5 shares on a lone marginal order, against the 1e-5 share tolerance written for continuous trading.
   - Each fill's allowance is now 2 units plus 2 × (pre-batch Δp) × 2b/(p(1−p)), computed from that batch's measured state difference. Each account's shares must stay within the sum of its own fills' allowances.
   - Prices, cash, payouts and MM PnL keep their original tolerances, and any fill/no-fill disagreement above one unit remains a failure.
   - An earlier draft of the per-account check derived its bound from the observed maximum, which is circular. It was replaced before any result was recorded.

---

## D-044 — Phase 2b result: FastEngine and the Solidity contracts agree
**Date:** 2026-10-10 · `docs/report/phase2b/` (`report.txt`, `gas_report.txt`, on-chain replay).

**Contracts:** MockUSDC, OutcomeShares (binary CTF), LMSRMarket (SD59x18 log-sum-exp, Gnosis-style inventory), TradeRouter (FastEngine fee semantics), OptimisticOracle (propose/dispute/settle).
- 31 Foundry tests, including 4 invariants × 4,096 fuzzed calls with 0 handler reverts: collateral = complete sets; q matches trader holdings; market-maker solvency within the b·ln 2 bound; price ∈ [0, 1].
- Fuzzing caught one real bug: a sell paid out before merging the returned pair. Fixed.

**EvmEngine:** the same `Engine` interface; Anvil FIFO with manual mining reproduces the builder's order exactly.

**Differential test (D-043 with its disclosed amendment), all PASS:**

| Scenario | Trades | max \|Δprice\| | max \|Δcash\| | max \|Δshares\| | MM PnL Δ (tol) | Flag mismatches | Boundary (pinned) |
|---|---|---|---|---|---|---|---|
| Fuzz (fees, bundles, protection) | 224 | 2e-16 | 1.3e-5 | 1e-14 | 4.3e-5 (2.2e-4) | 0 | 0 |
| E2a predator market, seed 3 m16 | 1,264 | 5e-16 | 8.7e-5 | 6e-14 | 3.0e-4 (1.3e-3) | 0 | 7 |
| No-predator market, seed 1 m1 | 988 | 4e-16 | 3.0e-5 | 3e-14 | 2.4e-4 (9.9e-4) | 0 | 0 |

**Milestone:** the archived front-run (block 23, market 16, seed 3) reproduces on the contracts trade for trade: same fills, same reverts, prices equal to 6 decimals (`python -m tfs replay sim/experiments/configs/e2a.yaml --seed 3 --market 15 --engine evm`).

**Fixed during 2b:** a float error in sell-amount conversion (`5.4537·1e6 = 5453699.999…`) silently dropped one unit per sell; regression test added.

**Gas (median):** LMSR buy ~158k, sell ~128k; router `execute` ~88k (up to ~323k when new complete sets are split); arbitrage bundle ~456k; oracle propose ~104k. Fed into Phase 3's cost reporting (SPEC §5.1).

**FastEngine unchanged:** the zero-predator digest test still passes; Phase 1/2a results are unaffected. The only FastEngine change is a read-only `quote()` and a `bankrolls` field in MarketRecord.

---

## D-045 — Owner decisions after Phase 2b; Phase 3 split; review date
**Date:** 2026-10-10

1. **Reversion correction accepted:** r = 1 is the pessimistic assumption about the predator. The disclosure wording for H2 is fixed in DISCLOSURES.md. **Phase 4 note:** add predator variants r ∈ {0, 0.5, 1} to the E7 tournament, to see which survives in equilibrium.
2. **Boundary cases** are reported as a count against total trades: 7 of 2,476 (0.28%). **The Phase 2b gas figures are the baseline** for Phase 3's verification-gas comparison (`docs/report/phase2b/gas_report.txt`: LMSR buy ~158k, sell ~128k, router execute ~88k, arbitrage bundle ~456k).
3. **Phase 3 is split.**
   - **3a:** SealedBatchAuction + Noir `sealed_order` circuit + COMMIT_REVEAL / ZK_BATCH policies + E3 (2×2 {predators 0/1} × {PUBLIC, ZK_BATCH}) + defense costs (batch interval K sweep, fill rate, non-reveal, proving time, verification gas).
   - **3b:** order-splitting expectiminimax (E4), whale (E5), oracle game (E6), shock scenarios.
4. **H3 is pre-registered before any 3a run.** Claude proposes thresholds, the owner ratifies. Components: H3a residual leakage against a metadata copy-trading predator; H3b anti-crowding with 0 predators; H3c cost as a function of K; plus the 2×2 interaction (anti-predator vs anti-crowding share of the benefit).
5. **Review planned for 31 October 2026.** Scope risk is tracked in each phase summary.

---

## D-046 — Phase 3a defense design (owner answers in plan mode) and H3 pre-registration
**Date:** 2026-10-10 · Plan approved, which ratifies the H3 thresholds. H3 is in `docs/PREREGISTRATION.md`, committed before any Phase 3a code or run.

1. **Batch clearing: uniform price with a pro-rata margin (replaces D-004's drop rule).**
   - Each order is normalised to a YES-price bound: buy-YES fills iff p ≤ L; buy-NO fills iff p ≥ 1 − L_NO.
   - The clearing price p* is the fixed point where the LMSR's average price for the net imbalance D(p*) equals p*. Orders strictly inside fill fully; orders whose bound equals p* fill pro-rata.
   - Budget balance as in D-004: YES pays p*, NO pays 1 − p*, matched pairs become complete sets, only D trades with the LMSR.
   - Solved by bisection, identically in Python and Solidity.
   - **Reason:** with rho = 1 researchers send identical limits, so D-004's "drop every violated order" empties whole batches.
2. **Sealed orders are buys only** (as in the SPEC §5 circuit). Exposure is reduced by buying the other side; YES+NO pairs are merged back to cash.
3. **Policies act on the main market.** The reference venue stays continuous and public. Under batching the arbitrageur is legged: its main leg clears in the batch, and the reference leg follows in the next block.
4. **Metadata in the reference setting:** commits come from the trader's own address, so a predator sees sender, block and escrow tier, not contents. Relayer variant: sender hidden.
5. **Timing:** a K-block commit window, then reveal and clearing in the next block; one order per identity per batch.
6. **Escrow tiers:** {5, 25, 125, 625} USDC, unused part refunded, non-revealers slashed.
7. **Monte Carlo treatment of ZK:**
   - validity enforced;
   - proving time adds a delay of ceil(bb prove seconds / 12) ticks;
   - real proofs only in the on-chain integration tests.
8. **The ZK-arm predator is a metadata copy-trader:**
   - from commit metadata (sender, tier) and per-address posteriors built from revealed orders, it infers the informed direction;
   - it joins the same batch, so it gets the same uniform price and cannot front-run;
   - it unwinds later (r = 1).

---

## D-047 — Metadata copy-trading predator and sealed-batch attackers (fixed before any E3 run)
**Date:** 2026-10-10 · Code: `agents/metadata_predator.py`, `agents/attackers.py`, `mempool/batch_desk.py`.

**Predator (ZK_BATCH arm, H3a).**
- Sees commit metadata (sender unless a relayer is used, block, escrow tier) and revealed orders, never contents.
- For each address it keeps μ_A, an EMA of that address's own post-fill markouts (its expected continuation).
- In the last block its proof allows, it predicts the batch's move Δ = Σ tier·d_A·μ_A / Σ tier over the identifiable committing addresses (d_A = last revealed direction). If EV > costs, it joins the batch in that direction with an EV-maximising size.
- No front-running gain is possible at a uniform price. Its exit keeps the expected aligned impact and |Δ|, minus its own impact (r = 1). It unwinds after H + 1 ticks by buying the other side.
- **Parameters:** exactly the reference predator's (D-034): capital 2·b, H = 10, threshold 0, EMA 0.1, min_profit 0.01, slippage 0.01, r = 1. No new tunable numbers.

**Change during development (disclosed).** The first version weighted addresses by P(informed) and learned drift only from addresses with P > 0.5, as the reference predator does. In a 6-market functional check (one seed, ZK_BATCH) no address ever passed that gate: a uniform-price batch prices informed demand at once and leaves little visible continuation. The predator therefore never traded, which would have made H3a trivially true, and the owner explicitly ruled out a trivially true H3. It was replaced by the per-address continuation estimate above, which has no gate. Afterwards it trades actively (76–250 shares per market in a 10-market check), with PnL near zero. No E3 run had been made.

**Attackers** (E3-V, descriptive; config `agents.attackers`, all 0 in the baseline):
- **Non-reveal griefer:** one commitment per batch, never revealed.
- **Free-option pair:** two staked identities commit opposite sides; after the honest reveals, only the side the batch is moving towards is revealed.
- **Spam committer:** insolvent orders posting the smallest tier. Slashed at reveal under commit_reveal; impossible under zk_batch.
- Each attacker uses size 10 shares (a typical informed order; forecaster max_order is 20) and a bankroll of 200 (as a forecaster). Their bankrolls run out as they are slashed, which bounds their effect; the reported numbers say so.

---

## D-048 — ZK toolchain, circuit, proving benchmark and verifier (Phase 3a step 4)
**Date:** 2026-10-10

- **Toolchain:** the global nargo 1.0.0-beta.16 and bb v2.1.8 are compatible (compile → witness → UltraHonk proof → verify checked), so no project-local install is needed. Neither global install was modified.
- **Poseidon2:** in this Noir version Poseidon2 is private in the standard library, so the circuit uses the external crate `noir-lang/poseidon` v0.1.1. On-chain, `zemse/poseidon2-evm` v2.0.0 (forge submodule) **matches Noir exactly** on test vectors for 1, 2 and 5 inputs (`test/Poseidon2Compat.t.sol`), so the keccak fallback is not needed.
- **Circuit** `circuits/sealed_order` (SPEC §5 + D-002): well-formed order; solvency (limit·size ≤ escrow); commitment = Poseidon2(side, limit, size, salt, secret); Merkle membership (depth 8) of Poseidon2(secret); nullifier = Poseidon2(secret, batch_id).
  - Units: limit in millionths, sizes and escrow in 6-decimal units.
  - The limit is a price for the side bought, so the worst case is limit·size for both sides. That is equivalent to SPEC's YES-price form.
  - 10 `nargo test`s: 2 valid, 8 invalid, each failing with its own reason.
  - Shared hashes live in `circuits/order_lib`. The helper circuit `order_hasher` computes public inputs for Python with the same code, so Python never re-implements Poseidon2.
- **Proving benchmark** (20 proofs, Apple M4 Pro, 14 threads): median **0.28 s**, p95 0.29 s (witness + UltraHonk proof, keccak transcript). The D-046 rule ceil(0.28 / 12) gives **proving_delay = 1 tick** in `base.yaml`. That is conservative against ZK: a 0.28 s proof fits inside one block, so the realistic delay is 0. The rule was fixed in advance and is kept; the conservatism is disclosed.
- **Verifier** (bb `write_solidity_verifier`): accepts the real proof and rejects a wrong escrow or batch id. Verification gas ≈ **2.81M** (vs Phase 2b LMSR buy ~158k: about 18×). The verifier's runtime code is **24,643 bytes, 67 over the EIP-170 limit** at optimizer runs 200, so it is not deployable on Ethereum as generated. Anvil runs with `--disable-code-size-limit`; this deployability cost is reported.
- **Solidity 0.8.26 → 0.8.27** for all contracts (the generated verifier requires ≥ 0.8.27; patch release, same semantics). All 35 Foundry tests pass after the bump.

---

## D-049 — SealedBatchAuction and IdentityRegistry (Phase 3a step 5)
**Date:** 2026-10-10

- **`SealedBatchAuction`:** commit (escrow tier; ZK: UltraHonk proof over [commitment, escrow, batch, nullifier, registry root]; commit-reveal: public nullifier keccak(sender, batch)) → reveal (Poseidon2 opening, checked on-chain with the library verified against Noir) → clear.
  - Clearing is the price ladder of `market/batch.py` in 18-decimal fixed point: interval scan, then the bound with integer bisection; margin rationed with matched pairs first, then the excess side pro-rata.
  - The net imbalance trades with the LMSR through TradeRouter, matched pairs are split into complete sets, fills pay the uniform price from escrow, the rest is refunded, and unrevealed or insolvent escrow is slashed.
- **Rounding** (found in review before testing):
  - the uniform price rounds *up* for the side that pays the LMSR, so payments always cover purchase plus sets;
  - per-order payments round up and are capped at the escrow.
- **`IdentityRegistry`:** staked registration; depth-8 Poseidon2 Merkle tree (the Yul Poseidon2 variant, verified against Noir vectors); `path(index)` gives the prover its siblings. The root is recomputed in full on each registration (about 255 hashes): a setup cost, not a per-trade cost.
- **`MockVerifier`:** test-only, accepts everything, used for clearing-maths differential tests over many orders.
- **Tests:** 47 Foundry tests in total, all passing, including:
  - commit/reveal/clear with conservation of USDC;
  - identical orders sharing pro-rata at the shared limit;
  - slashing (unrevealed; insolvent under commit-reveal);
  - nullifiers and timing;
  - a fuzzed random-batch property test (conservation, dust only, price in (0, 1));
  - a **real UltraHonk proof end to end**: commit, replay rejected, reveal, clear; about 5.5M gas for the whole batch.

---

## D-050 — EvmEngine sealed batches and their differential test (Phase 3a step 6)
**Date:** 2026-10-10 · `make difftest` now includes two batch scenarios; results in `docs/report/phase3a/difftest_report.txt`.

- **EvmEngine:**
  - `enable_batches(verifier_kind = mock | real | none)` deploys registry, verifier and auction. External libraries in the bb verifier (`ZKTranscriptLib`) are deployed and linked automatically.
  - `commit` takes its commitment from the contract's own `commitmentOf` (Poseidon2, cross-checked against Noir).
  - `clear_batch` mines the commitments, waits for the window to close, reveals and clears in one block, then merges YES+NO pairs, as FastEngine does.
- **Differential (D-043 amendment 4), both PASS:**
  - batch fuzz, 30 batches / 154 fills: Δprice 1.7e-9, Δcash 9.8e-6, Δfill 6e-7;
  - a traced zk_batch market with the metadata predator and the attackers, 40 batches / 506 fills: Δprice 1.8e-8, Δcash 4.1e-5, Δfill 1.8e-5 (within its derived allowance);
  - no fill/no-fill disagreements in either.
- **Real-proof integration test** (`tests/test_zk_integration.py`, 2.4 s): identity registered on-chain → Merkle path from the registry → Noir/bb proof (root equals the contract's root) → commit through the real UltraHonk verifier (replay rejected by the nullifier) → reveal → clear → filled.

---

## D-051 — E3 results: H3 verdicts as pre-registered (Phase 3a step 7)
**Date:** 2026-10-10 · Configs committed before any run (`9e8f06f`). All five experiments and `python -m tfs h3` exited 0. Archived in `docs/report/phase3a/` (`h3_verdicts.json`, one folder per experiment; the large `runs.csv` files stay in `results/`).

**Verdicts** (rules in PREREGISTRATION.md H3, computed by `tfs/experiments/h3.py`; joint paired bootstrap, 200 seeds, 10,000 resamples):

| | Statistic, point [95% CI] | Verdict |
|---|---|---|
| **H3a** residual leakage | L_PUB 0.130 [0.123, 0.138]; L_ZK 0.004 [−0.008, 0.015]; **R 0.03 [−0.06, 0.12]** (≤ 0.5) | **supported** |
| **H3b** anti-crowding | **P ratio 0.85 [0.83, 0.86]** (≤ 1.00); U_PUB − U_ZK −4.5 pp [−4.8, −4.3] | **contradicted** |
| **H3c** cost vs K | **ΔT(5) 17.2 ticks [16.5, 17.9]** (> 3K = 15); ΔT(20) − ΔT(1) −13.4 [−14.4, −12.4] | **contradicted** |
| **H3 overall** (E3-E) | **RMS truth change +43% [+36%, +51%]** (≥ 0); participation −2.9 pp [−4.8, −1.0] | **contradicted** |

H3c contradicted on its "compounds beyond 3K" branch. ΔT is not monotone in K. K = 1 is worst: ΔT(1) = 36.4, ΔT(2) = 24.0, ΔT(5) = 17.2, ΔT(10) = 20.7, ΔT(20) = 23.0. The one-predator arm is the same within about 1.5 ticks.

**2×2 decomposition (descriptive).** "Benefit" is the change from PUB to ZK.
- E3-F truth MSE: total −0.0116 (ZK worse); anti-crowding −0.0119; anti-predator +0.0004.
- E3-F researcher profit: anti-crowding −0.92 (batching itself lowers it); anti-predator +0.75 (sealing recovers the predator's take); net −0.16.
- E3-E truth MSE: anti-crowding −0.0156; anti-predator +0.0028.
- E3-E participation: batching lowers it by 8.6 pp without a predator; hiding recovers 5.6 pp of the predator's effect.
- The share statistics are not meaningful when the total has the "wrong" sign; the components are reported instead.

**Costs vs K** (E3-K, 0 predators; PUB reference fill 0.64, RMST 39.5):

| K | 1 | 2 | 5 | 10 | 20 |
|---|---|---|---|---|---|
| fill rate | 0.44 | 0.48 | 0.54 | 0.60 | 0.68 |
| exec delay (ticks) | 1.0 | 1.7 | 4.1 | 7.8 | 14.5 |
| truth MSE (PUB 0.0013) | 0.008 | 0.008 | 0.013 | 0.023 | 0.040 |
| RMST to ε | 75.8 | 63.4 | 56.6 | 60.1 | 62.5 |

- Proving: median 0.28 s per order (Apple M4 Pro), giving a 1-tick delay under the D-046 rule.
- Verification: about **2.81M gas** per sealed order. Phase 2b baselines: buy ~158k, sell ~128k, execute ~88k, bundle ~456k, so verification is about 18× a public buy.
- A whole batch with one real proof, end to end: about 5.5M gas.

**Variants (E3-V, E3-V-CR; descriptive):**
- **PRIVATE_RELAY** (hidden, but continuous) keeps truth MSE at the public level (0.0013), and the predator earns nothing. The accuracy loss under ZK comes from *batching*, not from hiding.
- **Relayer** (sender hidden): the metadata predator never trades, so this is identical to the 0-predator cell.
- **COMMIT_REVEAL without attackers** is ZK_BATCH with proving delay 0.
  - Researchers' unfilled share 0.28 vs ZK 0.57; researcher profit 5.62 vs 4.91.
  - Same truth MSE (0.0133).
  - The conservative 1-tick proving delay (D-048) is therefore responsible for most of ZK's fill cost, but not for its accuracy cost.
- **Attackers:**
  - The non-reveal griefer (40 unrevealed commits per market) and the spammer (commit-reveal only; impossible under ZK) each lose their whole 200 bankroll to slashing. Neither changes other agents' outcomes; only the aggregate fill rate falls, because their orders count as requested.
  - The free-option pair (still possible under ZK, which proves validity, not reveal) loses about 330 per market and raises truth MSE slightly (0.0143 vs 0.0132).
- **Predator r = 0.5 under ZK:** loses money (−1.7 per market).

**Diagnosis of the accuracy result** (run after the verdicts; descriptive; `docs/report/phase3a/diagnosis/`):
- Under sealed batches the main price **cycles around the researchers' shared belief instead of settling on it**. Tracking error |p − p*_full| is 0.071 (K = 1) and 0.078 (K = 5), vs 0.022 under PUBLIC and PRIVATE_RELAY.
- Mechanism:
  1. D-046 clears at the price where the LMSR's *average* price over the net imbalance equals p*. So the *marginal* price after clearing ends beyond every filled limit: about 0.88 for a shared belief of 0.73 from 0.53.
  2. All researchers then sell back to an average of 0.73, leaving the marginal price near 0.53, and so on.
  3. Identical researcher orders (ρ = 1) make the aggregate large. The proving delay sends two same-direction batches before anyone sees a clearing (K = 1).
- This is the designed clearing rule working as specified, not an implementation error. The FastEngine/EVM differential and the property tests confirm the rule is implemented as written.
- **The H3 accuracy and H3c verdicts are therefore conditional on average-price uniform clearing combined with agents that set their limit to their belief.** A clearing at the post-trade *marginal* price, or limit-aware order sizing, would be a different design. Neither is tried here: the verdicts stand as computed, and any such variant needs owner approval and would be exploratory.


---

## D-052 — Owner decisions after Phase 3a; verifier fits EIP-170
**Date:** 2026-10-10 · Owner.
1. **The H3 verdicts stand exactly as pre-registered** (D-051), with the disclosures as written.
2. **Exploratory X-4** (cannot change verdicts): one mechanism-side variant, *limit-respecting marginal clearing*.
   - The net imbalance trades through the LMSR only until the marginal price reaches the marginal order's limit.
   - Every fill is at that post-clearing marginal price.
   - The LMSR keeps the marginal-minus-average surplus, which is reported.
   - Runs: the 2×2 at K = 5, 200 paired seeds. Reported: accuracy, fills, predator take.
   - Scheduled after E4 and the shock scenarios.
3. **Proving delay in the report.** The measured proving time (0.28 s) is far below a block. The report presents commit-reveal (0 delay) as the realistic ZK outcome, alongside the pre-registered conservative 1-tick verdict. No new run.
4. **Verifier size.**
   - `optimizer_runs = 1` (`compilation_restrictions` in `contracts/foundry.toml`), applied to `SealedOrderVerifier.sol` only, gives **23,723 bytes**: 853 under EIP-170. `via_ir` fails on it (stack too deep).
   - Anvil no longer runs with `--disable-code-size-limit`; every contract now deploys under the real limit.
   - Cost: verification gas rises from about 2.81M to **2.84M** (+1%).
   - Per-batch proof aggregation (one recursive proof per batch) is noted as future work for the verification gas.
   - Note: when the compiler profile changes, `forge clean` is needed, otherwise stale flat artifacts are loaded.
5. **Remaining scope, in priority order:**
   1. E4 expectiminimax;
   2. shock scenarios (required by Topic 6: the stability analysis must show trend followers and arbitrageurs reacting);
   3. X-4;
   4. minimal dashboard and the report (drafting starts now, one section per phase);
   5. E5 whale (small);
   6. E6 oracle, only if time allows;
   7. Polymarket single calibration scenario;
   8. E7 tournament with predator r-variants (optional).

   All stretch goals are dropped.
6. **Phase 3b starts in plan mode**, with E4 and the shock scenarios first. E4 is pre-registered before it runs.

---

## D-053 — Phase 3b part 1 design (E4 and shock scenarios); H4 pre-registration
**Date:** 2026-10-10 · Owner answers in plan mode; plan approved. H4 is in PREREGISTRATION.md, committed before any E4 code.

**E4: the order-splitting game (SPEC §6.1)**
- **MIN is the rational worst-case predator.** It minimises MAX's profit, but only over front-runs that are profitable for itself under the simulation predator's own closed-form EV.
  - r = 1, P(informed) = 1, drift = competitor push.
  - The front-run is capped at x_max, so the victim still fills.
  - Why: under a pure zero-sum MIN, every slice it sees is pushed to MAX's limit regardless of cost. "Send everything at once" then tends to be optimal and the search becomes degenerate.
- **CHANCE nodes:**
  - noise flow (3 outcomes);
  - public news (probability = public rate; closes the public-information share of the gap);
  - a deterministic competitor push κ, measured on the no-predator PUBLIC baseline before any E4 run.
- **Search:** plain expectiminimax (the reference), plus alpha-beta on MAX/MIN, Star1 at chance nodes, move ordering and a transposition table.
- **Runtime:** the forecaster looks up the search's move at the nearest grid state (lazily filled policy table).
- **Primary population:** all forecasters use the rule under test. The single deviator is descriptive.

**Shock scenarios (descriptive; resolves Q1)**
- **False news** is part of the generative model. Every shock is false with known probability `q_false`, and its LLR is the exact mixture LLR. A correction published `correction_delay` ticks later turns it into the exact LLR. A scenario may force a shock's status. Defaults (q_false = 0) leave every earlier result unchanged.
- **Depeg** (minimal mechanistic model):
  - the main market's USDC is worth 1 − δ dollars for a window; the reference venue settles in an unaffected unit;
  - the dollar-valued arbitrageur trades only when its worst-case dollar payoff covers the dollar cost, so its band widens and arbitrage withdraws;
  - noise-trader withdrawal is a scenario input (swept), not a modelled result.
- **Stability metrics** (window 40 ticks): recovery, max deviation, overshoot, liquidity, trend-follower amplification (paired, trend 2 vs 0) and the arbitrageur's reaction. All are fixed in the plan before any run.

---

## D-054 — E4 game parameters measured; MIN uses the predator's measured beliefs (owner, before any E4 run)
**Date:** 2026-10-10 · Measured with `python -m tfs measure-env --seeds 50`. Archived: `docs/report/phase3b/environment.json`.

**Measurements** (baseline runs only, never E4 runs):
- **κ = 0.867.** This is the median share of forecaster 0's gap that *other* traders close in one block, in the no-predator PUBLIC baseline. IQR is [0.40, 0.99], from 337 ticks.
  - The first definition used every tick with a gap ≥ 0.1 and gave a median of 0. Most such ticks are equilibrium ticks: every researcher has reached its Kelly target and nobody trades.
  - Before any E4 run, the definition was corrected to the only case the game models: ticks where forecaster 0 sent an order. Both numbers are reported.
- **Reference predator (E2a baseline):**
  - P(informed) about forecasters, at season end: 0.196;
  - E[drift | informed]: 0.219 log-odds;
  - front-runs per forecaster order: 0.108 (it can front-run only one victim per block among about 10 researchers).

**Change to the D-053 MIN model** (owner decision, before any E4 run).
- D-053 had MIN use P(informed) = 1 and a drift equal to the competitor-closed gap. At κ = 0.87 that makes every slice worth about 0 (0.01–0.02 USDC), so the search's choice was noise.
- **MIN now uses the reference predator's measured beliefs** (P(informed) 0.196, E[drift] 0.219) in the same EV formula. It is still the worst case among the front-runs it expects to profit from, and it still sees every slice.
- Not adopted: a "targeted with probability 0.108" chance node (more faithful, but a weaker MIN and a slower search).
- With this change the search gives clear decisions, e.g. R/4 first, with values of 0.5–4 USDC.
- H4's thresholds and statistics are unchanged.

**Limitations (disclosed):**
- The searcher assumes competitors trade as in the capped-rule baseline (κ) and a predator with baseline beliefs.
- Both change when every forecaster uses the search, and the model does not adapt to that.

---

## D-055 — E4 results: H4 contradicted (as pre-registered)
**Date:** 2026-10-10 · Code and configs committed before any E4 run (`42743ad`; tree clean in `meta.json`). Archive: `docs/report/phase3b/e4/` (`h4_verdict.json`), `e4_v/`, `deviator/`, `e4_search/`.

**H4: CONTRADICTED** (joint paired bootstrap, 200 seeds, markets 6–30, one reference predator):
- **R4 = 0.901 [0.890, 0.912]**, entirely ≤ 1.00. The search rule earns about 10% *less* per researcher-market than the best simple rule, which is TWAP.
- **ΔL = +0.017 [+0.011, +0.024].** The search rule loses *more* of its edge to the predator than the capped rule.

| rule | researcher PnL, 0 pred | researcher PnL, 1 pred | leakage L [95% CI] | predator PnL | researcher reverts (1 pred) | truth MSE (0 pred) |
|---|---|---|---|---|---|---|
| capped | 5.93 | 5.16 | 0.130 [0.123, 0.138] | 5.76 | 61% | 0.00129 |
| naive | 5.95 | 4.56 | 0.234 [0.225, 0.245] | 10.06 | 65% | 0.00115 |
| twap | 6.13 | 5.62 | 0.083 [0.077, 0.088] | 4.06 | 20% | 0.00214 |
| random | 6.01 | 4.89 | 0.186 [0.179, 0.195] | 7.69 | 38% | 0.00144 |
| expectiminimax | 5.94 | 5.07 | 0.147 [0.140, 0.155] | 7.22 | 50% | 0.00123 |

**Descriptive:**
- R4 with no predator = 0.970 [0.963, 0.975]: even without a predator the search does not beat TWAP.
- **E4-V:**
  - depth 1, 2, 3, 4 give leakage 0.140, 0.143, 0.147, 0.144, so depth barely matters;
  - predator latency 0.05, 0.2, 0.5 gives leakage 0.142, 0.147, 0.159;
  - single deviator: forecaster 0 searching alone earns +0.06 [−0.21, +0.31] per market more than when it uses the capped rule like everyone else (100 seeds). No detectable individual gain.
- E4-V's chart step crashed on `users = None` after all data were written (84,000 rows, clean tree). The charts were redrawn from the saved CSVs with `tfs charts` (fix in `86108ba`); `run.log` keeps the traceback.

**Interpretation (for the report; not a re-test):**
- **TWAP wins on both counts.** Small fixed slices nearly remove crowding (reverts 20% vs 61%) and are less worth front-running (predator PnL 4.06 vs 5.76).
- **TWAP's cost is slower price discovery:** truth MSE without predators is about 65% higher than under the capped rule. It is a trade-off, not a free lunch.
- **The search's model misses the main force at play.** It models one trader against one predator, with a deterministic competitor push κ. It does not represent nine identical competitors sending orders at the same limit in the same block, so it cannot see that its own slices revert on that crowd.
- This is the rent-dissipation mechanism of F-002 again: crowding among identically informed researchers, not the predator, is the main execution problem in this world (ρ = 1). The pre-registered risk ("the search may behave like naive") was partly borne out.
- Better-informed searchers are possible: a model of the crowd, or measured predator targeting. They would be new designs, so they are not tried here.

---

## D-056 — Owner decisions after E4
**Date:** 2026-10-10 · Owner.
1. **The H4 verdict stands as pre-registered** (contradicted).
2. **Report framing for E4.**
   - Present algorithm correctness first: node-count benchmark, alpha-beta and Star1 savings, transposition-table hits, exactness tests.
   - Then strategy performance: it lost to TWAP because the game model omits the crowd (one predator plus a fixed competitor push, against nine identical researchers at the same limit).
   - Frame it as "minimax is only as good as its model of the game", citing that the pre-registration stated this risk.
3. **TWAP is privately best but socially costly** (truth MSE +65% vs capped without predators): an externality between the individual optimum and the market's accuracy. The report says so.
4. **Synthesis section** (`docs/report/synthesis.md`): the main adversary of an informed AI agent is the other informed agents sharing its signal, not the predator. It links F-002, H3b and H4 with their numbers.
5. **Order of the remaining work:**
   1. finish the benchmark;
   2. shock scenarios at 200 seeds;
   3. X-4 (status reported to the owner);
   4. **X-5** (EXPLORATORY, time-boxed to about half a day): a crowd-aware search that models the n − 1 same-signal competitors' flow as a chance node, using their observed policy. Compared with TWAP and capped; cannot change verdicts; reported even if it shows no gain;
   5. E5 whale (small);
   6. minimal dashboard;
   7. report.
6. **Review preparation:** `docs/report/walkthroughs/search.md`, a plain-language walkthrough of the search code with file and line references, worked example trees (also tests) and likely examiner questions.

---

## D-057 — Exploratory X-4 and X-5: designs fixed before their runs (EXPLORATORY; no verdict can change)
**Date:** 2026-10-10 · Code `036dc8a` (merged in `75cb203`). Configs `x4.yaml` and `x5.yaml`; analysis scripts in `docs/report/exploratory/x4/` and `x5/`.

**X-4: limit-respecting marginal clearing** (owner, D-052).
- `clear_batch(rule="marginal")`: the same price ladder, fixed point and pro-rata margin as D-046. The uniform price is the LMSR's *post-trade marginal* price for the imbalance, not its average price.
  - The market therefore ends exactly at the clearing price, never past a filled limit (property-tested).
  - Traders pay the marginal price. The LMSR keeps the surplus (marginal − average) × |D| ≥ 0, recorded per market as `lmsr_surplus`.
- **Runs:** the E3-F setting (research forced, markets 6–30, K = 5), {PUBLIC, COMMIT_REVEAL, ZK_BATCH} × {0, 1} predator, 200 seeds paired with E3-F's average-clearing cells.
- **Reported:** truth lost, fills, researcher profit, the predator's take (PnL and leakage), the surplus.
- **FastEngine only.** The Solidity SealedBatchAuction keeps the pre-registered average rule.

**X-5: crowd-aware order splitting** (owner, D-056; time-boxed).
- **The game gains a CHANCE layer between MAX and MIN:** the same-signal crowd trades ahead of MAX's slice in the same block.
  - Its five equally likely outcomes were measured on the no-predator capped baseline (`tfs measure-env`, 50 seeds, 337 trading blocks): the 10th–90th percentiles of the share of forecaster 0's gap that the other forecasters close before its own order executes, namely **0, 0.156, 0.647, 0.963, 1.0**.
  - The rest of the block's closure by everyone else is **κ_rest = 0.016**. So most of κ = 0.87 is the crowd trading ahead in the same block.
- **A slice that the crowd has already pushed past its limit reverts and earns nothing.**
- **The depth-cut-off heuristic is averaged over the crowd outcomes.** Found by a test: a crowd-blind heuristic credits profit the crowd would take.
- **Depth 2**, set from runtime alone before any X-5 run: depth 3 costs about 8 minutes per season, depth 2 about 105 s.
  - E4-V showed that depth barely matters for the plain search.
  - E4-V's depth-2 point gives the matched comparison. Depth 1 runs as a variant.
- **Post-crowd prices are snapped to the same 0.01 grid**, so the transposition table stays exact.
- **Runs:** the E4 setting, every forecaster using the rule, plus the single deviator, {0, 1} predator, 200 seeds. Compared with E4's capped, TWAP and search cells on the same seeds.
- **Limitation:** the crowd's distribution is measured with the competitors using the capped rule. When everyone searches, the crowd behaves differently, and the model does not adapt. The single deviator is the case where the measured crowd is exactly right.

**Defaults are unchanged** (average clearing, no crowd node). The E4 game is arithmetically identical, so earlier results reproduce exactly (digest test).

---

## D-058 — X-4 results (EXPLORATORY); owner framing of the defense; E4-search and shock results recorded
**Date:** 2026-10-10. X-4, E4-search and the shock runs all ran from the clean tree `106d419`. Archives: `docs/report/exploratory/x4/`, `docs/report/phase3b/e4_search/`, `docs/report/phase3b/shock_*`.

**X-4 (marginal batch clearing), against the pre-registered average rule on the same seeds:**
- ZK truth-lost RMS: −15.2% [−15.6, −14.7] without a predator, −13.8% [−14.2, −13.3] with one. Still about 2.7× PUBLIC.
- The remaining error is mostly a *lag*. Price minus p*_avail, signed towards the truth: −0.031; the sign flips 0.04 times per tick. The price moves once per 5-block batch, and each researcher sends one capped order per batch.
- The informed rent moves to the market maker:
  - LMSR surplus 47–50 per market;
  - researcher PnL falls from 5.0 to 1.2 per researcher-market;
  - the predator loses money.
- Commit-reveal with marginal clearing: RMS +145% vs PUBLIC; same rent transfer.

**Refinement of D-051** (descriptive, disclosed). At K = 5 the average rule's error flips sign only 0.05 times per tick (20 seeds): much of it is lag, not only cycling around the belief. The cycling is stark at K = 1. D-051's general description at K = 5 should read "overshoots and lags".

**Owner framing for the report (Act 3 conclusion): trust vs accuracy.** Hiding orders from the predator works two ways:
- **By trust** (PRIVATE_RELAY): accurate, and the predator earns nothing, but users must trust the relay.
- **By cryptography** (ZK_BATCH): trustless, but batching imposes lag. The clearing rule only decides whether the price overshoots (average) or the market maker takes the rent (marginal).
- **Untested future work** (no run): a hybrid rule. Check limits at the marginal price (no overshoot), charge the average price, and rebate the surplus pro rata. It might avoid both the overshoot and the rent loss, but not the lag.

**E4-search (descriptive):** 500 states from E4 seasons; every pruned value equals plain expectiminimax (≤ 2.2e-16). Nodes per decision at depth 4:

| plain | alpha-beta | + Star1 | + ordering | + transposition table |
|---|---|---|---|---|
| 89,862 | 86,425 | 82,348 | 39,045 | 3,469 (197 → 10.5 ms) |

- Alpha-beta alone saves little: the predator usually has a single allowed front-run.
- Star1 cuts nodes but costs time.
- The transposition table dominates, because grid states recur.

**Shock scenarios (descriptive):**
- **True news:** absorbed in about 7–8 ticks.
- **False news:** the correction is the most stressed moment (max deviation 0.20–0.29).
- **Trend followers:** they trade with every move (+3 to +46 shares) but barely amplify it (overshoot ≤ +0.007; recovery often 1–2 ticks faster).
- **Depeg:** arbitrage withdraws (venue gap 0.12 → 0.26, volume −30%); main accuracy is unchanged.
- **Batching after news:** recovery doubles (6.9 → 13.5 ZK, 14.7 commit-reveal).

---

## D-059 — E5 design: what is measured (fixed before the run; descriptive, no hypothesis)
**Date:** 2026-10-10 · Owner approval (time-boxed). Code on branch `e5-whale` (`769ff89`, `67dc5b6`, `27b653f`), config `e5.yaml`.

- **Whale:** from tick 100 to 140 it buys to hold the price of the outcome that will happen at 0.30, until its budget is spent.
  - It never observes the outcome; the scenario picks its side, as a forced-false shock does.
  - A whale pushing *toward* the truth would just be a lucky trader, not manipulation (found in a smoke run: +158 profit).
  - **The report labels this scenario an adversarial worst case** (owner), like the forced-false shock, not a model of typical whales.
- **Setting:** the reference setting (one 200-tick market, research forced, no predator, PUBLIC), but with **no news shock**, so the whale is the only event. 200 seeds.
- **Sweep:** whale budget {50, 200, 800} × arbitrageur {off, on}. Each point is paired with its budget-0 twin (same arbitrageurs). A budget-0 whale is tested to leave the market bit-identical to no whale.
- **Measured over [100, 200):**
  - **target on the wrong side** (owner): the share of the window in which the whale's target lies further from the true outcome than p*_avail. This verifies manipulation rather than assuming it; when the available information itself favours the wrong outcome, the whale is not pushing against it;
  - deviation × duration: Σ |price − p*_avail|, as the excess over the twin;
  - max deviation;
  - ticks off by ≥ ε;
  - **correction time:** ticks from the whale's last trade until the price is back within ε of p*_avail for good;
  - the whale's PnL;
  - **who collects the loss:** paired PnL differences by agent kind (forecasters, public-news trader, noise, arbitrageur, trend) and the two market makers.

---

## D-060 — E5 results: the cost of manipulation (descriptive; adversarial worst case)
**Date:** 2026-10-11 · Run from the clean tree `7f1b903`. Archive: `docs/report/phase3b/e5/` (`e5.csv`, `e5_paired.csv`, `e5_deviation.png`). 200 paired seeds.

- **Manipulation verified, not assumed.** The whale's target was on the wrong side of p*_avail in 94.5% of its window ticks. In the other 5.5%, the available information itself favoured the wrong outcome.
- **Price distortion grows with the budget.** Paired against the budget-0 twin, no arbitrageur:

| budget | deviation × duration (Σ\|p − p*\| over 100 ticks) | extra ticks off by ≥ ε | whale PnL |
|---|---|---|---|
| 50 | +2.8 [2.4, 3.1] | +30 [25, 34] | −39 |
| 200 | +11.2 [10.2, 12.2] | +72 [68, 77] | −171 |
| 800 | +39.7 [37.3, 42.2] | +87 [85, 90] | −648 |

  The whale loses about 80% of its budget.
- **Who collects the whale's loss** (budget 800, arbitrageur on):
  - researchers +526 (about 80%);
  - public-news trader +54;
  - main market maker +55;
  - arbitrageur +22 and reference market maker +16;
  - trend followers *lose* 18: they chase the whale's push.

  Without the arbitrageur the researchers collect slightly more (+559).
- **The arbitrageur reduces the distortion only a little** (+36.8 vs +39.7 at budget 800). It imports the reference venue's public-news-only price, which is less informed.
- **The distortion outlasts the whale.** After the whale stops, |price − p*_avail| levels off at about 0.04, 0.12 and 0.39 (budgets 50, 200, 800) until the market ends. The "correction time" is censored in most runs: the price is not back within ε by the end.
  - **Mechanism, checked:** after the whale, researchers trade less (23 shares in the last 50 ticks vs 166 with no whale), and already hold 1.56× their combined Kelly target (1.23× without a whale).
  - Informed capital is at its Kelly limit, so nobody pushes the price back: the limits of arbitrage (Shleifer & Vishny 1997, cited for the mechanism).
  - This depends on the fixed per-market bankrolls (D-015) and quarter-Kelly sizing. More informed capital would correct further.
- **Labelled in the report as an adversarial worst case** (owner, D-059), not a model of typical whales.

---

## D-061 — X-5 results (EXPLORATORY; completed about 7 h past its time box; included by owner decision)
**Date:** 2026-10-11 · Run from the clean tree `106d419`, with the spec and seeds of the committed `x5.yaml`.
- **Timing.** The first attempt (14 workers) was killed when the Claude session ended. It was restarted unchanged with 8 workers, which give byte-identical results. It finished at 09:29 against a 02:30 time box: about 7 hours over.
  - The machine stayed awake (a sleep assertion held throughout).
  - The overrun came from the cost estimate, which scaled a 6-market timing linearly to 30 markets.
- **Owner decision:** include X-5 regardless of outcome, labelled EXPLORATORY and "completed about 7 h past its time box".
- **Archive:** `docs/report/exploratory/x5/` (`analysis.txt`, `results/`).

**Results** (E4 setting, 200 paired seeds, markets 6–30):

| rule | P, 1 predator, / TWAP | P, 0 predators, / TWAP | leakage | researcher reverts |
|---|---|---|---|---|
| capped | 0.918 [0.907, 0.928] | 0.968 | 0.130 | 0.61 |
| search (E4-V, depth 2) | 0.906 [0.895, 0.916] | 0.970 | 0.143 | 0.50 |
| **crowd-aware search, depth 2** | **0.917 [0.907, 0.927]** | 0.970 | **0.132** | 0.48 |
| crowd-aware search, depth 1 | 0.913 [0.902, 0.923] | 0.970 | 0.137 | 0.49 |
| TWAP | 1 | 1 | 0.083 | 0.20 |

- **Adding the crowd to the model helps a little:** +0.011 over the plain search at the same depth, with leakage back to the capped level. It closes about a tenth of the gap to TWAP.
- **Single deviator:** forecaster 0 searching alone with the crowd model earns +0.12 [−0.17, +0.41] per market over the capped rule. No detectable individual gain.
- **Interpretation (not a test).** TWAP's advantage looks like a *population* effect: when everyone sends small slices, the crowd ahead shrinks for everyone. A best response to the crowd *as observed* (measured under the capped rule) cannot find that. Whether TWAP pays for a single deviator was not tested.

---

## D-062 — Owner decisions: X-5 framing, dashboard plan; streamlit dependency
**Date:** 2026-10-11 · Owner.
1. **X-5 framing in the report:** TWAP's edge is a population effect, the gap between a single agent's best response and the multi-agent outcome. "Does TWAP pay off for a single deviator?" is untested future work (E7 tournament).
2. **Dashboard plan approved** (offline; precomputed results; only the search tree computes live). Views:
   1. front-run replay;
   2. PUBLIC vs ZK side by side;
   3. expectiminimax tree with pruned branches and node counts;
   4. shocks and stability;
   5. verdicts.

   Additions:
   - a landing page walking the four acts in demo order;
   - PNG fallbacks of each view's key figure in `dashboard/fallback/`;
   - `make dashboard`, setup documented in the README, and a fresh-install run tested from a clean clone.
3. **New dependency:** `streamlit`, in an optional `dashboard` extra. Reason: the SPEC's dashboard (§9), and CLAUDE.md names `streamlit run dashboard/app.py`. Charts reuse matplotlib; nothing else is added.
4. **Order:** build the dashboard while the owner reviews report sections 4–6. Sections 1, 7 and 9 are drafted after that review.

**Built and tested** (2026-10-11): code `1c34a5a`; data and fallbacks built from that clean tree (`74f2fb3`).
- **Fresh-clone test:**
  - `git clone` → `make setup` → `pytest -q`: 837 passed, 8 skipped (EVM/ZK need `.tools/`, as documented);
  - `make dashboard-data` reproduces the committed data exactly, apart from the provenance stamp;
  - `make dashboard` serves (health check ok).
- **Dashboard tests:** every page renders without errors, including each shock scenario and the real-game trees at depths 1 and 2. Block 23 of the replay is the archived Phase 2a front-run.

---

## Open questions

- **Q1 — RESOLVED 2026-10-10: false news stays off until Phase 3; implemented in Phase 3b as D-053.** Original question: False news vs the MSE decomposition (D-001). SPEC §2 allows *false* breaking news (a signal pointing the wrong way, later corrected). If the ideal prices treat a false shock as a genuine high-precision signal, they are not using the true likelihood, and the cross term will not vanish. Proposed fix: make false news part of the generative model with a known probability `q_false`, so the ideal prices discount shocks accordingly. Agents may still over-react; that is a market failure and shows up as aggregation loss. Needs owner decision before Phase 1 implements shocks.
- **Q2 — RESOLVED 2026-10-10 by D-032** (binding pre-registration; three Claude-chosen details flagged).
- **Q3 — RESOLVED 2026-10-10:** review planned for 31 October 2026 (D-045).
- **Q4 — RESOLVED 2026-10-10 by D-031 (project-local install).** Global install: `forge Version: 1.3.5-foundry-zksync-v0.1.7` (checked 2026-10-10). Option: `FOUNDRY_DIR=~/.foundry-stable foundryup` installs stable binaries to a separate directory (foundryup reads `FOUNDRY_DIR`), used by this project via a Makefile/env var. Alternatively keep using foundry-zksync's forge, which compiles standard EVM by default. Decide before Phase 2b.
- **Q5 — RESOLVED 2026-10-10 by D-024 (correlated signals) and D-026 (baseline calibration).** Original question: Private-information aggregation (F-001). The market as specified prices little private information. Options: keep it and report it; change how agents read the price; or change the information structure (e.g. Grossman–Stiglitz-style shared research signal). Owner decision needed before Phase 2a, because H2's mechanism depends on it.
- **Q6 — RESOLVED 2026-10-10 by D-029** (add informed capital to the calibration; fallback rule).
