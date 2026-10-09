# Pre-registration of Hypothesis Verdict Criteria

> **Status: DRAFT — not yet binding.** The items marked **TO CONFIRM** must be settled by the owner. The commit that removes this banner is the pre-registration, and it must precede any E2a run. git history is the evidence.

Rules that apply to every hypothesis:
- All comparisons are **paired**: the treatment and its baseline run on the same seeds (same signals, same noise-trader draws), with N seeds as set in the experiment config (default 200).
- CIs are 95%, computed over seeds.
- Truth lost and its parts are measured as MSE against `p*_full` (SPEC §2) and reported as RMS. Shares ("accounts for the majority") are computed in MSE units, where the decomposition is additive.
- The verdict is taken at the **reference setting** named below. The full sweep is always reported alongside it.
- These criteria are not edited after the experiment runs. Any change is logged in `docs/DECISIONS.md` and disclosed in the report.

---

## H1 — Short run (tested by E2a)

*With participation fixed, front-running mostly redistributes profit from informed traders to predators, and truth lost rises only modestly.*

**Measured on:** the first market of each season (participation fixed by the initial research decisions), predator setting vs the paired no-predator baseline.

Let `L` = leakage ratio (share of informed traders' no-predator edge captured by predators), and `Δ` = relative increase in truth-lost RMS vs the no-predator baseline.

| Verdict | Condition (owner's criteria) |
|---|---|
| **Supported** | `L ≥ 0.30` **and** `Δ ≤ 15%` |
| **Contradicted** | `Δ > 30%` |
| **Partly supported** | anything else |

**TO CONFIRM — how the 95% CI enters:**
- *Proposed (strict):* Supported requires the CI of `L` to lie entirely ≥ 0.30 **and** the CI of `Δ` to lie entirely ≤ 15%. Contradicted requires the CI of `Δ` to lie entirely > 30%.
- *Alternative (lenient):* compare point estimates to the thresholds, and report CIs alongside.

**TO CONFIRM — reference setting:** which predator count and latency the verdict is taken at (proposed: the E2a default config, 1 predator at default latency, with values written here before commit).

**TO CONFIRM — leakage ratio denominator:** proposed as the informed traders' mean PnL in the paired no-predator run (their "theoretical edge"), so `L = (predator PnL attributable to front-running informed orders) / (informed no-predator PnL)`.

---

## H2 — Long run (tested by E2b)

*When research is a choice, predators shrink research participation, and truth lost rises sharply.*

| Verdict | Condition (owner's criteria) |
|---|---|
| **Supported** | participation falls by **≥ 25 percentage points** over a season **and** participation loss accounts for **the majority (> 50%)** of the increase in truth lost |
| **Contradicted** | **TO CONFIRM** — not yet specified |
| **Partly supported** | **TO CONFIRM** — presumably anything else |

**TO CONFIRM — "falls ≥ 25 pp over a season" relative to what:**
- *Proposed:* participation in the **final stretch** of the predator season is ≥ 25 pp lower than in the final stretch of the **paired no-predator season**. Both seasons start from identical initial conditions, so this isolates the predators' causal effect. Without predators, participation may also drift as forecasters compete away each other's profit.
- *Alternative:* the drop from market 1 to the final stretch *within* the predator season.

**TO CONFIRM — "final stretch":** proposed as the last 10 of the season's 30 markets.

**TO CONFIRM — "majority of the increase":** proposed as `ΔMSE_participation / ΔMSE_truth_lost > 0.5` (predator vs paired baseline, final stretch, MSE units), with the same CI rule chosen for H1.

**TO CONFIRM — contradicted criterion:** suggestion only (owner to choose): *contradicted* if the participation gap's 95% CI lies entirely below 10 pp (predators do not meaningfully reduce research).

---

## H3 — Defense (tested by E3)

To be pre-registered before E3 runs (Phase 3).
