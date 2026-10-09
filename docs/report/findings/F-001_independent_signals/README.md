# F-001: With independent private signals, a Kelly-betting market prices the average belief, not the pooled evidence

**Status:** E1 finding, kept for the report (owner decision 2026-10-10). The default model then moved to correlated research signals (DECISIONS D-024).
**Produced at:** commit `599b7ea` (clean tree). Every file in this folder was regenerated there; `meta.json` files record it.

## Setup
- Base configuration (`e1/config.yaml`): 10 forecasters, each researching with **independent** Gaussian private signals of about 0.2 nats per market (≈ 2 nats pooled), against ≈ 2 nats of public news plus a 1-nat shock.
- Forecasters bet fractional Kelly (k = 0.25) on an LMSR (b = 100). Single markets, everyone researches, no predators, 200 seeds per point.
- Belief model `own_signals`: each forecaster combines the prior, public news and its own signals, and ignores the price. The alternative `price_anchored` model was also run.

## Result
| Quantity (base config, 200 seeds) | own_signals | price_anchored |
|---|---|---|
| Truth-lost RMS vs p*_full [95% CI] | 0.178 [0.162, 0.192] | 0.245 [0.236, 0.254] |
| Share of research information priced (`research_captured`) | **0.09** | −0.74 |
| Runs settling within ε of p*_avail after the shock | ≈ 11% | ≈ 2% |

- `research_captured` = 1 − E[(p − p*_avail)²] / E[(p_public − p*_avail)²]. It is 0 for a price that ignores all research and 1 for a price equal to the pooled posterior. The market price stays close to the public-news-only posterior (RMS ≈ 0.05).
- More forecasters make truth lost *worse* (`e1/e1_sweeps.png`): more evidence exists, but little more of it is priced.
- Diagnostics (100 seeds each) rule out the obvious alternatives. Removing the arbitrageur, or the arbitrageur and the main public-news trader, changes little. A 10× forecaster bankroll changes little under `own_signals`.

## Explanation
- Each forecaster's belief is dominated by the shared public news (≈ 2 nats) and moved only slightly by its own private signals (≈ 0.2 nats).
- The pooled posterior p*_avail *adds* the independent private log-likelihood ratios. A market of Kelly bettors instead moves toward a wealth-weighted *average* of beliefs, so it reflects roughly one forecaster's worth of private evidence.
- Under `price_anchored`, fractional Kelly stops each agent long before its unpriced information is in the price, and noise-trader moves are never reverted.

## Relation to the literature
Beygelzimer, Langford & Pennock (2012) show that when every trader bets by the Kelly criterion, the market's price is the **wealth-weighted average of the traders' beliefs**. They also show that fractional Kelly behaves like full Kelly with beliefs shrunk toward the market price.
- Source: A. Beygelzimer, J. Langford, D. Pennock, *Learning Performance of Prediction Markets with Kelly Bettors*, arXiv:1201.6655, 2012. Extended abstract at AAMAS 2012.
- Verified 2026-10-10: arXiv abstract page, and the AAMAS 2012 proceedings entry listed in search results.
- **Scope of the comparison:** their result is for a market where Kelly bettors trade with each other at an equilibrium price. Our market has an LMSR market maker, latencies, noise traders and a capped one-order-per-tick execution. The paper is offered as the explanation of the mechanism, not as a proof that our simulation must behave this way. Our numbers are what we measured.

## What this means for the project
- Under independent private signals, research participation can only change market accuracy a little. That would mute H2 for a reason unrelated to predators.
- The owner therefore moved the default to correlated research signals (DECISIONS D-024) and kept this result as an E1 finding.

## Files
- `e1/`: the E1 sweep (both belief models; forecaster count, precision, b): `summary.csv`, `runs.csv`, `per_market.csv`, `e1_sweeps.png`, `config.yaml`, `meta.json`
- `season_baseline/`: 30-market season, endogenous research. Participation falls from 100% to ≈ 22% and stays there (`season_baseline.png`).
- `calibrate_costs/`: the D-017 cost calibration used for that season (cost_median 5.45)
- `plots/market_seed1.png`, `plots/market_seed2.png`: single-market price paths
