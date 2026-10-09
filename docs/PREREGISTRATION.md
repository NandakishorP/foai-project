# Pre-registration of Hypothesis Verdict Criteria

**Status: BINDING for H1 and H2.** Committed before any E2a or E2b run, and before any predator code exists. git history is the evidence. H3 is pre-registered separately, before E3 runs.

**Frozen baseline.** Commit `067fa2f` (DECISIONS D-030): `sim/experiments/configs/base.yaml` and `season_baseline.yaml`.
- Correlated research with rho = 1: one shared research signal, the textbook Grossman–Stiglitz setting.
- Informed capital: bankroll / b = 2. Research cost median 1.716.
- Belief model `own_signals`. No-predator steady-state participation 55%; share of research information priced 0.70.
- None of these values change for E2a or E2b.

**Amendments (all before any E2 run):** D-033 (E2a design, predator memory). Any change to this file after an E2 run has started is logged in `docs/DECISIONS.md` and disclosed in the report, with the reason.

---

## Rules common to H1 and H2

1. **Paired design.** Every predator run has a no-predator twin on the same master seed. Common random numbers: the signals, noise-trader orders and research-exploration draws are identical. N = 200 seeds per configuration.
2. **Confidence intervals.** 95%, from a paired bootstrap over seeds: 10,000 resamples, percentile intervals, fixed bootstrap seed 0. The resampling unit is the seed, so each resample keeps a run together with its twin.
3. **"Clears a threshold" means the whole CI clears it** (strict rule). A point estimate alone never decides a verdict.
4. **Truth lost** is the RMS of the market price against p*_full (SPEC §2). Relative change: Δ = RMS_predators / RMS_baseline − 1, computed from pooled MSEs (ratio of sums over seeds).
5. **Reference setting.** The verdict is taken at the reference predator configuration in `sim/experiments/configs/e2a.yaml` / `e2b.yaml`. That configuration is one predator at its default latency. Its parameters are fixed in those files, with rationale, in the commit that adds the predator, before any E2 run, and they are not changed afterwards. The full sweeps (number of predators, latency, research-cost distribution) are always reported alongside the reference verdict.
6. **Descriptive, not pass/fail:** the split of truth lost into aggregation and participation loss, predator PnL, builder revenue and noise-trader loss are reported for every experiment but do not enter any verdict.

---

## H1 — Short run (E2a)

*With a fixed set of informed traders, front-running mostly redistributes profit from informed traders to predators, and truth lost rises only modestly.*

**Measured on (amended 2026-10-10, before any E2 run, D-033):** 30-market seasons with research **forced on** (`research.mode: always`), so participation is fixed at 100% with and without predators. Predator beliefs about addresses persist across the season, because addresses are stable. H1 is scored on **markets 6–30**; markets 1–5 are a warm-up in which the predator learns who is informed. (Originally: the first market of each season, which would have scored a predator that had not yet learned anything.)

- **Leakage ratio** L = 1 − Σ informed PnL (predators) / Σ informed PnL (no predators), summed over seeds and scored markets: the share of the informed traders' (forecasters') no-predator edge that is lost when predators are present. Predator PnL is reported next to it, to show where the edge went.
- **Δ1** = relative change in truth-lost RMS, predators vs paired baseline (rule 4).

| Verdict | Condition |
|---|---|
| **Supported** | CI(L) entirely ≥ 0.30 **and** CI(Δ1) entirely ≤ +15% |
| **Contradicted** | CI(Δ1) entirely > +30% |
| **Partly supported** | anything else |

---

## H2 — Long run (E2b)

*When forecasters choose each market whether research is worth its cost, predators shrink research participation, and truth lost rises sharply.*

**Measured on:** the **final stretch**, markets 21–30 of 30-market seasons (the calibration steady state, D-026/D-029), endogenous research. Predator beliefs persist across the season (amendment D-033).

- **Participation gap** G = participation (no predators) − participation (predators), in percentage points, pooled over the final stretch.
- **Δ2** = relative change in truth-lost RMS over the final stretch, predators vs paired baseline (rule 4).

| Verdict | Condition |
|---|---|
| **Supported** | CI(G) entirely ≥ 25 pp **and** CI(Δ2) entirely > +30% |
| **Contradicted** | CI(G) entirely < 10 pp **or** CI(Δ2) entirely ≤ +15% |
| **Partly supported** | anything else |

Notes fixed in advance:
- **Headroom.** The no-predator steady state is 55% participation, so a 25 pp gap means predators push steady-state participation to 30% or below.
- **"Rises sharply" (> +30%)** is set at H1's contradiction threshold, so a long-run rise counts as sharp only if it is larger than anything H1 tolerates as "modest". The 15% in the contradiction rule mirrors H1's "modest" bound.
- **How the mechanism appears in the decomposition (rho = 1).** Every researcher sees the same research signal, so a single researcher already makes p*_avail = p*_full, and participation loss is zero whenever anyone researches. Researcher exit therefore mainly **removes informed capital** that pushes the price toward p*_avail. That is the Grossman–Stiglitz channel, and it appears as *aggregation* loss, not participation loss. This is why H2 is judged on total truth lost and participation, and the aggregation/participation split is reported only descriptively. Participation loss becomes non-zero only in markets where nobody researches.

---

## H3 — Defense (E3)

To be pre-registered before E3 runs (Phase 3).
