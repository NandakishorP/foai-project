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

## Open questions

- **Q1 — False news vs the MSE decomposition (D-001).** SPEC §2 allows *false* breaking news (a signal pointing the wrong way, later corrected). If the ideal prices treat a false shock as a genuine high-precision signal, they are not using the true likelihood, and the cross term will not vanish. Proposed fix: make false news part of the generative model with a known probability `q_false`, so the ideal prices discount shocks accordingly. Agents may still over-react; that is a market failure and shows up as aggregation loss. Needs owner decision before Phase 1 implements shocks.
- **Q2 — Pre-registration details.** See the "TO CONFIRM" items in `docs/PREREGISTRATION.md`.
- **Q3 — Review date.** Not yet supplied.
- **Q4 — Stable Foundry alongside foundry-zksync.** Option: `FOUNDRY_DIR=~/.foundry-stable foundryup` installs stable binaries to a separate directory (foundryup reads `FOUNDRY_DIR`), used by this project via a Makefile/env var. Alternatively keep using foundry-zksync's forge, which compiles standard EVM by default. Decide before Phase 2b.
