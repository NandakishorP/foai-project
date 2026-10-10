# Disclosures for the report

Everything a reader needs to judge whether the results were steered. Each item points to its DECISIONS entry.

## Choices made after looking at simulation output
| What | When / evidence | Entry |
|---|---|---|
| Belief model chosen by a pre-declared rule (`own_signals`) after E1 | Rule fixed in the approved Phase 1 plan; 40-seed debugging smoke run disclosed | D-016, D-022 |
| Research costs, informed capital and rho set by calibration | Calibration of the *no-predator* baseline only. Rules committed before each run; full grids archived; round 1 found no feasible point and was reported | D-017, D-026, D-028, D-029, D-030 |
| Default information model changed to correlated research (rho) | Owner decision after finding F-001 (independent signals are barely priced); F-001 kept as a finding | D-024, F-001 |
| Four predator fixes (revert protection, slot pricing, `own_impact_reversion`, no unwindable positions) | Found in single-seed functional debugging, before any E2 run; ratified by the owner | D-034, D-037 |

## Pre-registration details chosen by Claude (owner gave no number), ratified by the owner after the results
- H2 "rises sharply" = whole CI of Δ truth-lost RMS above +30%.
- H2 contradiction rule: CI(G) entirely < 10 pp, or CI(Δ2) entirely ≤ +15%.
- Leakage ratio = share of the informed traders' no-predator edge *lost* with predators.
Source: D-032; ratification D-037. Committed before any E2 run (`b803d95`, amended `c677dab`).

## Differential-test tolerance amended after the first run (Phase 2b)
The D-043 tolerances were stated before the test existed. After the first run (D-043 amendment):
1. The MM-PnL tolerance became n_trades × 1e-6, derived from per-trade rounding in the market maker's favour. The original fixed 1e-4 was mis-specified.
2. Both engines receive the same 6-decimal-quantized orders.
3. Trades whose average price is within 1e-6 of their limit have their fill/revert decision pinned to FastEngine's and are listed. Predators deliberately push victims onto their limits, below the chain's one-unit resolution. **Count: 7 of 2,476 trades (0.28%) across the three scenarios.** Per scenario: 0 of 224 (fuzz), 7 of 1,264 (predator market), 0 of 988 (no-predator market).

Every other comparison stays at full strictness, and any fill/revert disagreement away from a limit fails the test.

## Runs that failed or were repeated
- E2a first attempt crashed (overflow) and wrote no results; fixed and rerun from a clean commit (D-035).

## Modelling assumptions that favour or disfavour the predators
- `own_impact_reversion = 1`: the reference predator assumes other traders undo its own price impact before it exits. This is the pessimistic assumption for the predator, so the measured harm may be a lower bound. See D-037 for why LMSR path independence does not by itself imply r = 1. Exploratory X-1 varies r.
- The reference predator holds rather than sandwiches; the sandwich variant is reported (higher leakage, about 0.28).
- Identical predators bid identically, so the same one always wins the slot; several predators of the same type therefore behave much like one.

## Sensitivity of the H2 verdict (must appear next to the verdict in the report)
**H2 is contradicted under the pre-registered predator.** That predator assumes other traders undo its own price impact before it exits (`own_impact_reversion` r = 1), which is the pessimistic assumption for the predator (D-037). It gives participation gap 6.0 pp [4.5, 7.6] and Δ truth lost +11% [+6, +17].

**Under r = 0.5, a viable and more aggressive predator, the same rule gives "partly supported"**: 10.4 pp [8.8, 12.1] and +18% [+14, +24] (exploratory X-1). **The verdict is sensitive to predator aggressiveness.** Neither setting comes near "supported" (≥ 25 pp and > +30%). An r = 0 predator is not viable: it loses about 178 per market.

Follow-up (Phase 4): predator variants r ∈ {0, 0.5, 1} enter the E7 tournament, to see which survives in equilibrium (D-045).

## Phase 3a (ZK sealed batches, E3) — must appear next to the H3 verdicts
- **What the H3 verdicts depend on** (D-051).
  - H3a is supported: sealing removes essentially all leakage, even against a metadata-reading predator.
  - H3b, H3c and H3 overall are contradicted. Under the pre-registered clearing rule (D-046: uniform price = the LMSR's *average* price over the net imbalance), the main-market price cycles around the researchers' shared belief instead of settling, which makes accuracy and time-to-ε worse.
  - These verdicts hold **for that clearing rule with agents that set their limit to their belief.** Other batch designs (clearing at the post-trade marginal price; limit-aware order sizing) were not tested.
  - PRIVATE_RELAY, which hides orders without batching them, keeps public-level accuracy.
- **Proving delay is conservative against ZK** (D-048).
  - A proof takes 0.28 s, well inside a 12 s block, but the pre-fixed rule gives a 1-tick delay.
  - Commit-reveal without attackers is the same mechanism with zero delay. It has researchers' unfilled share 0.28 vs 0.57 and profit 5.62 vs 4.91 per researcher-market, with the same truth MSE. So the delay drives most of ZK's fill cost and the H3b profit result, but not the accuracy result.
- **Verifier size** (D-048, D-052). As generated (optimizer runs 200), the bb UltraHonk verifier is 24,643 bytes, 67 over EIP-170, and the E3 runs used Anvil with the size limit disabled. Recompiled alone with optimizer runs = 1, it is 23,723 bytes. Anvil now enforces the limit, and every on-chain test passes under it. Verification costs about 2.84M gas per sealed order at runs = 1 (2.81M at runs 200), about 18× a public buy (~158k). The E3 simulation results do not depend on this: they run on FastEngine. Future work: per-batch proof aggregation.
- **Realistic ZK outcome** (D-052). The report shows commit-reveal (0 proving delay) as the realistic ZK outcome, next to the pre-registered verdict computed with the conservative 1-tick delay.
- **Metadata predator changed before any E3 run** (D-047). Its first version gated on P(informed) > 0.5 and never traded under batching, which would have made H3a trivially true. It was replaced by a per-address markout EMA before any E3 run.
- **Batch differential tolerance** (D-043 amendment 4). Batch fill comparisons use an allowance derived from the price difference between engines, not a fixed number. Fill/no-fill disagreements still fail the test (there were none).
- **Diagnosis run after the verdicts.** The oscillation analysis (`docs/report/phase3a/diagnosis/`) was done after seeing the results, to rule out a bug. It is descriptive and changes no verdict.

## Exploratory analyses
Everything under `docs/report/exploratory/` is exploratory. It was not pre-registered and never alters a verdict.
