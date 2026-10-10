# EXPLORATORY robustness checks X-1 to X-3

> **Exploratory.** Declared in DECISIONS D-039 before running, but not pre-registered. Nothing here alters the H1/H2 verdicts (H1 partly supported, H2 contradicted; D-036, ratified D-037).

All runs use the reference predator setting, 200 paired seeds and the same paired statistics as the verdicts (paired seed bootstrap, 10,000 resamples). Code commit `f98a78e`, clean tree. Each folder holds `paired.csv`, `summary.csv`, `config.yaml` and `meta.json`.

Columns:
- **Δ truth** — change in truth-lost RMS, predators vs no predators.
- **G** — participation gap, in percentage points.
- **L** — leakage: share of the informed traders' edge lost.

E2a rows score markets 6–30; E2b rows score markets 21–30.

## X-1 — How much does predator strength depend on `own_impact_reversion` (r)?

| Setting | r | Δ truth | G (pp) | L | Predator PnL/market | Informed PnL/market (no pred → pred) |
|---|---|---|---|---|---|---|
| E2a | **1 (reference)** | +3.4% [+3.2, +3.7] | — | 0.13 [0.12, 0.14] | +5.8 | 59.3 → 51.6 |
| E2a | 0.5 | +11.6% [+10.9, +12.2] | — | 0.20 [0.19, 0.21] | +6.6 | 59.3 → 47.5 |
| E2a | 0 | +155% [+153, +158] | — | −1.95 | **−178** | 59.3 → **175** |
| E2b | **1 (reference)** | +11.1% [+6.2, +17.0] | 6.0 [4.5, 7.6] | 0.15 [0.13, 0.16] | +5.4 | 50.7 → 43.3 |
| E2b | 0.5 | +18.4% [+13.6, +24.0] | 10.4 [8.8, 12.1] | 0.21 [0.19, 0.22] | +6.8 | 50.7 → 40.3 |
| E2b | 0 | +1.9% [−5.4, +10.5] | **−34** [−37, −31] | −2.37 | **−176** | 50.7 → **171** |

**Reading.**
1. **r = 0 is not a stronger predator; it is a self-destroying one.** Expecting its own impact to persist, it buys large positions. Other traders trade the impact away before it exits, and it loses almost its whole bankroll (about −177 per market from 200). That money goes to the informed traders. In E2b, research then becomes so profitable that participation *rises* from 55% to 89%. This confirms D-037: other traders do undo the predator's impact, so path independence alone does not make the round trip free in this market.
2. **r = 0.5 is a viable, more aggressive predator, and it roughly doubles every harm measure.** Applied mechanically to the H2 rule, the r = 0.5 numbers would read "partly supported" rather than "contradicted": the gap's CI [8.8, 12.1] is no longer entirely below 10 pp, and Δ's CI [+13.6, +24.0] is no longer entirely ≤ +15%. **The H2 verdict is therefore sensitive to how aggressive the predator is.** It is still far from "supported" (25 pp, +30%). This sensitivity is disclosed in the report (DISCLOSURES.md).

## X-2 — Does the participation gap keep widening over 60-market seasons?

| Markets | G (pp) | Δ truth | Participation (no pred → pred) | L |
|---|---|---|---|---|
| 21–30 | 6.0 [4.5, 7.6] | +11.1% [+6.2, +17.0] | 55.2% → 49.2% | 0.15 |
| 31–40 | 5.3 [3.9, 6.6] | +5.1% [+0.7, +9.7] | 51.7% → 46.5% | 0.14 |
| 41–50 | 5.1 [3.9, 6.4] | +7.5% [+3.8, +11.6] | 51.1% → 46.0% | 0.15 |
| 51–60 | 4.7 [3.5, 6.0] | +10.4% [+6.3, +14.8] | 49.4% → 44.7% | 0.16 |

**Reading: no.** The gap does not widen. It is stable to slightly narrowing (about 6 → 5 pp). Participation drifts down slowly in both arms; the no-predator drift was noted at calibration (D-032). The predator effect is a stable level shift, not a cumulative collapse.

## X-3 — Is researcher crowding robust to staggered research arrival?

Research reaches each researcher 0–3 ticks after it is emitted (`max_delay: 3`), compared with simultaneous arrival in the same run.

| Setting | Arrival | Researcher trades reverting (no pred → pred) | Δ truth | G (pp) | L |
|---|---|---|---|---|---|
| E2a | simultaneous | 55.7% → 61.4% | +3.4% [+3.2, +3.7] | — | 0.13 |
| E2a | staggered 0–3 | 50.4% → 57.2% | +3.5% [+3.2, +3.8] | — | 0.16 |
| E2b | simultaneous | 34.9% → 36.5% | +11.1% [+6.2, +17.0] | 6.0 [4.5, 7.6] | 0.15 |
| E2b | staggered 0–3 | 31.3% → 32.8% | +16.9% [+12.1, +22.3] | 8.4 [7.1, 9.6] | 0.20 |

**Reading.**
- Crowding is robust. Even when researchers learn the same news up to three blocks apart, about half of their trades (everyone researching) or a third (endogenous participation) revert on their own limits, because others with the same information got there first.
- Staggering helps predators a little (L 0.16–0.20; gap 8.4 pp). Researchers are less synchronised, so each early mover leaves more room to front-run.
