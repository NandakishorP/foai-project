# Truth for Sale — Report (DRAFT)

*Status: draft, written phase by phase. Numbers are copied from the archived results named in each section. Verdicts follow `docs/PREREGISTRATION.md`. Everything that must appear next to a verdict is in `docs/report/DISCLOSURES.md` and is repeated here where it applies.*

## 1. Question and hypotheses
On a public blockchain, pending orders are visible before they execute. In an on-chain prediction market, a trader who paid for research reveals that research through its orders. A "predator" that watches the mempool can trade ahead of it.

We ask how much "truth" (forecast accuracy) such a market loses to predators, and whether a zero-knowledge sealed-order batch auction restores it, and at what cost.
- **H1 (short run):** with a fixed set of informed traders, front-running mostly redistributes profit, and truth lost rises only modestly.
- **H2 (long run):** when research is a choice, predators shrink research participation and truth lost rises sharply.
- **H3 (defense):** a ZK sealed batch auction restores participation and accuracy at a measurable cost.
- **H4 (smart execution, added before E4):** search-based order splitting keeps more of the informed edge than the best simple execution rule.

Verdict rules were committed before each experiment ran (git history is the evidence).

## 2. Course concepts and where they are in the code
| Concept | Where |
|---|---|
| Agents with PEAS descriptions | every class in `sim/tfs/agents/` |
| Belief states (Bayesian updating) | `agents/beliefs.py` (log-odds updating); predator's Beta posterior per address (`agents/predator.py`) |
| Utility-based decisions | fractional Kelly (`agents/kelly.py`); predator's expected-value front-run sizing |
| Search | arbitrageur's optimal size; predator's grid search |
| Adversarial search | order-splitting expectiminimax with alpha-beta (`sim/tfs/search/`, Phase 3b) |
| Topic 6 agents | arbitrageur (cross-venue), trend follower, noise traders, shock events |

## 3. Phase 1 — The world (information model, market, baseline)
- **Information model** (SPEC §2): binary outcome; Gaussian public news and research signals; exact Bayesian ideal prices p*_full (all potential information) and p*_avail (information actually acquired).
- **Truth lost:** MSE of the market price against p*_full. It splits additively into aggregation loss and participation loss; a test checks that the cross term vanishes across seeds (D-001).
- **Market:** an LMSR main market and a smaller public-news-only reference venue. Agents: informed forecasters (Bayesian, fractional Kelly), public-news traders, noise traders, a cross-venue arbitrageur, trend followers.
- **Finding F-001.** With independent research signals the market priced only about 9% of the research information, because Kelly traders move the price toward the *average* belief. The owner chose correlated research signals with an exact posterior (D-024).
- **Calibration** (pre-declared rule, D-029/D-030): the baseline froze at ρ = 1 (one shared research signal, the Grossman–Stiglitz textbook case), informed capital 2 × b, and cheap research. This gives 55% steady-state participation and 70% of the research information priced.
- **Limitation:** only ρ = 1 met both calibration criteria. At ρ = 1, researcher exit shows up as aggregation loss, not participation loss.

## 4. Phase 2 — Predators (H1, H2) and on-chain fidelity
**Predator** (D-034): a Beta posterior per address from post-trade markouts; front-runs when expected value net of exit slippage and builder bid is positive. Reference parameters were fixed before any run.

**H1 — partly supported** (E2a, 200 paired seeds, markets 6–30):
- truth-lost RMS +3.4% [+3.2, +3.7];
- leakage 0.130 [0.123, 0.138] (the threshold was ≥ 0.30).

**H2 — contradicted** (E2b, markets 21–30):
- participation gap 6.0 pp [4.5, 7.6];
- truth lost +11% [+6, +17].

**Sensitivity disclosed with the verdict:** a more aggressive viable predator (r = 0.5) would give "partly supported" (10.4 pp; +18%). The pre-registered verdict stands.

**Finding F-002:** most research rent is lost to researchers competing on the same signal, not to the predator (Holden & Subrahmanyam 1992).

**Phase 2b:** Solidity contracts (LMSR in PRBMath fixed point, outcome shares, router, oracle) agree with the Python engine in a differential test. The prices match to 1e-15, and the archived front-run replays on-chain trade for trade. Gas: LMSR buy about 158k.

## 5. Phase 3a — The defense (H3)
**Mechanism** (D-046):
- sealed buy orders committed with a Noir/UltraHonk validity proof (Poseidon2 commitment, escrow solvency, identity-set membership, nullifier);
- revealed and cleared every K = 5 blocks at one uniform price, with a pro-rata margin, netting through the LMSR.

**Costs** (SPEC §5.1):
- proof 0.28 s;
- verification about 2.84M gas, about 18× a public buy;
- the verifier fits EIP-170 only when compiled with optimizer runs = 1;
- execution delay about 4 ticks at K = 5.

**Verdicts** (E3, 200 paired seeds):

| | Result | Verdict |
|---|---|---|
| H3a residual leakage | R = 0.03 [−0.06, 0.12] | supported |
| H3b anti-crowding | profit ratio 0.85 [0.83, 0.86] | contradicted |
| H3c delay cost vs K | ΔT(5) = 17.2 ticks [16.5, 17.9] | contradicted |
| H3 overall | truth-lost RMS +43% [+36, +51] | contradicted |

**Next to the verdicts (DISCLOSURES):**
- Under the pre-registered clearing rule (uniform price = the LMSR's *average* price), the price cycles around the researchers' shared belief. Accuracy and reaction speed get worse. Hiding orders without batching (PRIVATE_RELAY) keeps public-level accuracy, so the loss comes from batching, not from hiding.
- The 1-tick proving delay is conservative. Commit-reveal (zero delay) is presented as the realistic ZK outcome: researchers' unfilled share 0.28 vs 0.57, with the same accuracy.
- **Exploratory X-4** (marginal-price clearing; D-058):
  - it removes the overshoot and cuts ZK's truth-lost RMS by 14–15%, but ZK stays about 2.7× the public level, because batching lags;
  - it moves the research rent to the market maker: researcher profit falls from 5.0 to 1.2 per researcher-market.

**The Act 3 conclusion: trust vs accuracy.** Hiding orders from the predator works two ways:
- **By trust** (PRIVATE_RELAY): accurate, and the predator earns nothing, but users must trust the relay.
- **By cryptography** (ZK_BATCH): trustless, but batching imposes a lag. The clearing rule only decides whether the price overshoots (average price) or the market maker takes the rent (marginal price).
- **Untested future work:** a hybrid rule, with the limit check at the marginal price, average-price charging and a pro-rata rebate of the surplus. It might avoid both the overshoot and the rent loss, but not the lag.

## 6. Phase 3b — Smart execution (H4) and market stability under shocks

### 6.1 The search algorithm: correct and efficient
- **The order-splitting game** (SPEC §6.1). Each block the forecaster (MAX) picks a slice, the predator (MIN) picks a front-run, and chance moves the price (noise, news, other traders).
- **How it is solved:** depth-limited expectiminimax with alpha-beta at MAX/MIN nodes, Star1 pruning at chance nodes, move ordering and an exact transposition table on a state grid. A plain-language walkthrough with worked trees is in `docs/report/walkthroughs/search.md`.
- **Correctness.** Every combination of the speed-ups returns exactly the plain expectiminimax value, on 620 random games and on the real game.
- **Efficiency** (500 states from E4 seasons, depth 4): nodes per decision fall from 89,862 for plain expectiminimax to 3,469 with every speed-up, and time from 197 ms to 10.5 ms. The transposition table does most of the work, because grid states recur. Alpha-beta alone saves only 4%: the predator usually has a single allowed front-run, so MIN nodes rarely have alternatives to cut. Star1 removes nodes but costs more time than it saves. Full table: `docs/report/walkthroughs/search.md` §6.

### 6.2 The strategy: H4 contradicted
- **Result** (pre-registered, 200 paired seeds): the search rule earned 0.901 [0.890, 0.912] of the best simple rule, TWAP. It also lost *more* of its edge to the predator than the Phase 1–3a rule (+1.7 pp [+1.1, +2.4]).
- **The search is correct for its game, but the game leaves out the main force.** It models one predator and a fixed competitor push. In the market, nine other researchers with the same signal send the same order at the same limit in the same block. TWAP's small slices avoid that crowd (researcher reverts 20% vs 61%), and beat the search even with no predator (0.970 [0.963, 0.975]).
- **Minimax is only as good as its model of the game.** This risk was written into the pre-registration before the run.
- **Private optimum, social cost.** TWAP is the best private response, but it slows price discovery: truth MSE is about 65% higher than under the capped rule without predators (0.00214 vs 0.00129). Each researcher who slows down keeps more rent and leaves the price further from the truth for longer: an externality between the individual and the market optimum.
- **Exploratory X-5** (crowd-aware search) tests whether adding the crowd to the model closes the gap. *(to be added)*

### 6.3 Market stability under shocks (Topic 6; descriptive, metrics fixed in D-053 before any run)
One 200-tick market per seed, 200 seeds, research forced, no predator. Archive: `docs/report/phase3b/shock_*`, with `stability.csv`, `amplification.csv` (paired, trend followers on vs off) and the event-study and flow plots.

**True breaking news (S-T).** At tick 100 a true shock arrives. Everyone knows 20% of breaking news is false, so it is discounted until confirmed 20 ticks later.
- The market absorbs it within about 7–8 ticks: restricted time-to-ε 7.9 ticks at 1 nat, 7.1 at 3 nats.
- Main-market volume rises about 3× in the 20 ticks after the shock, against the 20 before.
- The arbitrageur carries the news to the slower reference venue, which lags by a few ticks in the plots.

**False breaking news (S-F).** The shock points the wrong way and is corrected 20 ticks later.
- The price follows the false news as far as the ideal posterior does: the shock is discounted by q_false, not ignored.
- At the correction it has to reverse. That is the most stressed moment in any scenario: max |price − p*_avail| reaches 0.20 (1 nat) and 0.29 (3 nats).
- Arbitrage volume roughly doubles at the correction (63–90 shares vs 32–41 after the shock).
- The less the market doubts the news (q_false 0.1 vs 0.4), the larger the reversal.

**Trend followers react, but barely amplify.** Paired, trend followers on (2) vs off:
- They clearly trade in the direction of every move: +3 to +46 shares within the window. Every CI is above 0 except one (1-nat false shock with q_false 0.4: +3.3 [−0.0, +6.7]). After a false-news correction they chase the reversal (+15 to +46 shares).
- Their effect on the price is small:
  - overshoot rises by at most 0.007 in probability (detectable only for large or false shocks);
  - max deviation changes by less than 0.006;
  - recovery is often *faster* with them, by 1–2 ticks (e.g. −1.0 [−1.8, −0.3] ticks after a 1-nat true shock), because they push in the direction the information is already taking the price.
- Two trend followers of 2 shares a tick are small against researchers who move the price by tens of shares in one block. The result is specific to that size.

**Collateral depeg (S-D).** The main market's USDC is worth 0.90 dollars for 30 ticks; there is no news.
- **The arbitrageur reacts by withdrawing.** Against the no-depeg control:
  - the cross-venue gap more than doubles (mean |logit gap| 0.12 → 0.26);
  - arbitrage volume falls by about 30% (36.8 → 25.8 shares);
  - the gap's half-life rises from 19 to 23 ticks.
- **Main-market accuracy is essentially unchanged** (max deviation 0.096 in both). Researchers keep the informed price; the reference venue is what decouples.
- **Noise-trader withdrawal** (an input) lowers volume and activity (traders active per tick: ratio 0.99 → 0.59 when all noise traders leave). It does not hurt accuracy.

**Batching delays the reaction to news (S-K; SPEC §5.1).** The same true shock under each policy:
- recovery doubles: 6.9 ticks public, 13.5 ZK batch, 14.7 commit-reveal;
- max deviation rises from 0.10 to about 0.16, and overshoot doubles;
- the cross-venue gap widens about 4×, because the arbitrageur's batched leg is late.

The plots show the price moving in K = 5-block steps and lagging p*_full by about 10 ticks. This is the cost side of the defense, consistent with H3c.

(In these runs p*_avail equals p*_full, because ρ = 1 and everyone researches. The two lines coincide in the plots.)

### 6.4 Manipulation: a whale backing the wrong outcome (E5; adversarial worst case)
A whale holds the price of the outcome that will happen at 0.30 from tick 100 until its budget runs out. This is a worst case by construction, like the forced-false shock, not a model of typical whales. Its target was really on the wrong side of the best available estimate in 94.5% of its window.

- **Cost and distortion grow with the budget.** Budgets of 50, 200 and 800 lose 39, 171 and 648 (about 80%). Extra deviation × duration is +2.8, +11.2 and +39.7 probability-ticks.
- **Informed traders collect most of the loss** (about 80%; budget 800: +526). The public-news trader, the market makers and the arbitrageur take the rest. Trend followers lose by chasing the whale.
- **The distortion outlasts the whale.** After a large whale stops, the price stays about 0.39 away from the ideal posterior until the market ends. Researchers already hold more than their Kelly targets, so nobody has the capital or the incentive to push it back: the limits of arbitrage. This depends on the model's fixed bankrolls and quarter-Kelly sizing.

### 6.5 Synthesis
See `docs/report/synthesis.md`: across F-002, H3b and H4, the main adversary of an informed agent is the other informed agents sharing its signal, not the predator.

## 7. Phase 4 — Real-world calibration, tournament, dashboard
*(to be written)*

## 8. Limitations and honesty notes
*(collected from DISCLOSURES.md at the end)*

## 9. Prior work
*(SPEC §13; never claim "first")*
