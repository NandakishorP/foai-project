# Synthesis: the main adversary of an informed AI agent is the other informed agents

*Status: report section, written after the H1–H4 verdicts. It connects results that were tested separately. It is an interpretation of pre-registered results, not a new test, and changes no verdict. Numbers come from the archives named in each line.*

## The finding
The project was designed around one adversary: a mempool predator that spots informed orders and trades ahead of them. In every experiment, though, the largest loss for an informed agent came from **the other informed agents trading on the same signal**. They send the same orders, in the same block, at the same limit. The predator taxes what remains.

This holds in the frozen baseline: ρ = 1, so every researcher receives the same research signal (D-030), the Grossman–Stiglitz textbook case. It is the "common information" setting of Holden & Subrahmanyam (1992), where identically informed traders race and reveal their information quickly, competing the rents away.

## Three independent lines of evidence

### 1. The rent is split by competition, not taken by the predator (F-002, Phases 1–2)
- **Total informed profit per market saturates while the number of researchers grows** (E1, no predators): 36.9 with 2 researchers, 58.6 with 10, 60.5 with 20. Per researcher it falls roughly as 1/n.
- **Researchers crowd each other out:** 56% of their trades revert on their own limits with no predator present (E2a), because researchers ahead of them already pushed the price there.
- **Others close 87% of a trading forecaster's remaining gap in a single block** (κ, no-predator baseline; D-054).
- **The predator takes a modest share:** leakage 0.130 [0.123, 0.138] (H1), about 5–6 per market. Steady-state participation falls by only 6.0 pp [4.5, 7.6] (H2, contradicted).

### 2. Removing the predator's view does not remove the problem (H3, Phase 3a)
- **Sealing orders works against the predator:** residual leakage under ZK is 0.004 [−0.008, 0.015]; H3a supported.
- **Batching makes crowding worse, not better (H3b contradicted).** Researchers' unfilled share rises from 52.8% to 57.3%, and their profit falls to 0.85 [0.83, 0.86] of the public level with no predator present.
  - Identical limits meet one uniform price, so everyone is rationed pro-rata.
  - The price cycles around the shared belief (D-051).
- **In the 2×2 decomposition of researcher profit** (E3-F):
  - hiding orders from the predator is worth **+0.75** per researcher-market;
  - the crowding side of batching costs **−0.92**.

  The crowd term is the larger.
- **Prediction recorded in D-038:** batching would relieve crowding ("the anti-crowding effect may be the larger of the two"). It was larger, but with the opposite sign to the one predicted. Under the pre-registered clearing rule, batching amplified crowding.

### 3. Smart execution against the predator loses to dumb execution against the crowd (H4, Phase 3b)
- **H4 is contradicted:** the expectiminimax order-splitting rule earns 0.901 [0.890, 0.912] of the best simple rule (TWAP).
- **The search optimises against a predator**, with the other researchers reduced to a fixed push κ. It does not model nine identical researchers sending orders at the same limit in the same block.
- **TWAP's advantage is almost entirely about the crowd:**
  - researchers' reverts fall from 61% to 20%;
  - it beats the search even with **no predator at all** (R4 at 0 predators = 0.970 [0.963, 0.975]);
  - it also leaks least to the predator (0.083, vs 0.130 for the capped rule and 0.147 for the search), because small slices are not worth front-running.
- **Search depth barely matters** (leakage 0.140–0.147 at depths 1–4). With 87% of the gap gone after one block, there is little future left to search.

## What it means
- **For the hypotheses.** H1 and H2 posit a predator big enough to matter. H3 posits a defense against it. H4 posits a better response to it. All three under-weigh the crowd, and the verdicts reflect that:
  - H1 partly supported;
  - H2 contradicted;
  - H3 contradicted overall, although H3a is supported;
  - H4 contradicted.
- **For the market.** What is best for an individual and what is best for the market diverge.
  - TWAP is the best private response, but it slows price discovery: truth MSE is about 65% higher than under the capped rule without predators (0.00214 vs 0.00129).
  - Each researcher who slows down keeps more of its rent and leaves the price further from the truth for longer. That is an externality between the individual optimum and the market's accuracy.
  - Defenses aimed at predators (sealed batches) do not address it, and can make it worse.
- **For agent design.** An agent's adversarial model must include its peers. In the search walkthrough's words: *minimax is only as good as its model of the game.* The exploratory X-5 (a crowd-aware search) tests whether adding the peers to the model is enough.

## Limits
- **ρ = 1 is the extreme of shared information.** It was the only setting that met the calibration criteria (D-030). With independent research (ρ = 0) there is less crowding, but also far less information priced (F-001).
- **The predator is the pre-registered reference** (r = 1). A more aggressive viable predator roughly doubles its tax (X-1, r = 0.5: leakage 0.20–0.21). That is still smaller than the crowding losses above.
- **All of this is in simulation.** Polymarket is used only for calibration (SPEC §8). No claim is made that real markets are front-run through a public mempool.
