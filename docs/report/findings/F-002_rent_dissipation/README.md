# F-002: Competition among informed traders dissipates research rents; predators tax a small pie

**Status:** finding for the report (owner decision 2026-10-10). It explains *why* H2 was contradicted. It does not change any verdict.

## Claim
- In the frozen baseline (rho = 1: every researcher receives the same research signal), the main limit on research profits is **other researchers**, not predators.
- The informed traders' total profit per market is roughly fixed. Competition splits it, and their own trades crowd each other out.
- Predators take a modest share of an already small pie, so they cannot drive research participation down sharply.

## Evidence

**1. The pie is fixed; competition splits it.** E1, single markets, everyone researches, no predators, 200 seeds (`docs/report/phase1_milestone/e1/summary.csv`):

| Researchers | Total informed PnL / market [95% CI] | Per researcher | Researchers' reverted trades / market* |
|---|---|---|---|
| 2 | 36.9 [33.4, 40.4] | 18.5 | 11 |
| 5 | 52.4 [46.4, 58.3] | 10.5 | 66 |
| 10 | 58.6 [49.8, 67.3] | 5.9 | 254 |
| 20 | 60.5 [48.5, 72.4] | 3.0 | 858 |

\* All reverted trades per market; with no predators they are almost entirely researchers hitting their own limits.

Total profit saturates around 60 while profit per researcher falls roughly as 1/n.

**2. Crowding inside a block.** The replay `docs/report/phase2a/replay/replay_seed3_m15_block23.txt` (and `.png`) shows block 23 of market 16, seed 3, at the E2a setting:
- All ten researchers receive the same signal and send YES buys with the same limit (0.683).
- The predator front-runs the first one (15 shares, bid 0.21).
- Two more researchers fill. Six of the remaining researchers' orders revert on their own limit, because researchers ahead of them have already pushed the price to it.
- The predator's front-run cost the first researcher a little. The other researchers cost each other most of the block.

**3. Crowding measured** (EXPLORATORY X-3, `docs/report/exploratory/`). Share of researchers' trades that revert:
- E2a (everyone researches): 55.7% without predators, 61.4% with one.
- E2b (endogenous participation, markets 21–30): 34.9% without, 36.5% with.
- If research reaches researchers 0–3 ticks apart instead of at once, the share is still 50.4% (E2a). Crowding does not depend on perfectly simultaneous news.

**4. The predator's tax** (E2a/E2b reference, `docs/report/phase2a/`):
- Informed PnL falls from 59.3 to 51.6 per market (E2a; leakage 0.13) and from 50.7 to 43.3 (E2b; 0.15).
- The predator nets about 5–6 per market.
- Against a research cost of about 1.7 per researcher per market, this lowers steady-state participation by only 6 pp (55% → 49%).
- A more aggressive viable predator (EXPLORATORY X-1, r = 0.5) roughly doubles the tax (leakage 0.20–0.21; gap 10 pp). That is still far from the collapse H2 posits.

## Relation to the literature
Holden & Subrahmanyam (1992) extend Kyle (1985) to several insiders who share the same long-lived private information. They find the insiders **compete aggressively and reveal most of their common information very quickly**. In the limit of continuous trading, market depth becomes infinite and all private information is revealed immediately, in contrast with Kyle's single monopolist, who trades gradually. Fast revelation means the rents are competed away.

Our rho = 1 baseline is their common-information case. Researchers race to trade on the same signal, the price incorporates it within a few blocks (E1: 96% of research information priced), and per-researcher profit falls roughly as 1/n.

- Source: C. W. Holden and A. Subrahmanyam, "Long-Lived Private Information and Imperfect Competition", *Journal of Finance* 47(1), 247–270, March 1992.
- Verified 2026-10-10: RePEc/IDEAS record (bibliographic details and abstract). The full text is behind JSTOR, so only the abstract-level claim is cited.
- Scope: their model is a Kyle-style auction with a market maker setting prices from aggregate order flow. Ours is an LMSR with limit orders and a block builder. The paper is cited for the mechanism (competition among identically informed traders dissipates rents through fast revelation), not as a proof that our numbers must come out this way.

## What this means for the project
- **H2's mechanism** (predators shrink research) is present but small. Predators tax a pie that competition has already made small, and the research decision depends on what is left.
- **Prediction for Phase 3** (recorded as D-038): batching (ZK_BATCH) changes two things at once:
  - it removes the predator's view of orders (anti-predator effect);
  - it stops researchers from crowding each other within a block (anti-crowding effect: one uniform price per batch).

  E3's 2×2 {predators 0/1} × {PUBLIC, ZK_BATCH} separates them. F-002 suggests the anti-crowding effect may be the larger of the two.
