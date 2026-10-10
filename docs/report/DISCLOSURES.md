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

## Runs that failed or were repeated
- E2a first attempt crashed (overflow) and wrote no results; fixed and rerun from a clean commit (D-035).

## Modelling assumptions that favour or disfavour the predators
- `own_impact_reversion = 1`: the reference predator assumes other traders undo its own price impact before it exits. This is the pessimistic assumption for the predator, so the measured harm may be a lower bound. See D-037 for why LMSR path independence does not by itself imply r = 1. Exploratory X-1 varies r.
- The reference predator holds rather than sandwiches; the sandwich variant is reported (higher leakage, about 0.28).
- Identical predators bid identically, so the same one always wins the slot; several predators of the same type therefore behave much like one.

## Sensitivity of the H2 verdict (must appear next to the verdict in the report)
H2 was **contradicted** at the pre-registered reference predator (r = 1): participation gap 6.0 pp [4.5, 7.6], Δ truth lost +11% [+6, +17]. In exploratory X-1, a more aggressive but still profitable predator (r = 0.5) gives 10.4 pp [8.8, 12.1] and +18% [+14, +24]. The same rule would read that as **partly supported**. Neither setting comes near "supported" (≥ 25 pp and > +30%). The verdict stands as pre-registered; its sensitivity to predator aggressiveness is a limitation (D-040).

## Exploratory analyses
Everything under `docs/report/exploratory/` is exploratory. It was not pre-registered and never alters a verdict.
