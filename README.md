# Truth for Sale

An adversarial multi-agent simulation of an on-chain prediction market. Informed AI forecasters trade on private research. A predator reads the public mempool and front-runs them. A zero-knowledge sealed-order batch auction is the defense. The project measures how much "truth" (forecast accuracy) the market loses, and what the defense restores at what cost.

- **Design:** `docs/SPEC.md`
- **Decisions:** `docs/DECISIONS.md`
- **Pre-registered hypotheses:** `docs/PREREGISTRATION.md`
- **Report (draft):** `docs/report/REPORT.md`
- **Disclosures:** `docs/report/DISCLOSURES.md`

## Setup
Requirements: macOS or Linux, [uv](https://docs.astral.sh/uv/), and Python 3.12 (uv installs it if missing).

```bash
make setup          # creates .venv and installs the package with dev, evm and dashboard extras
make test           # Python test suite (about 1.5 minutes)
```

Optional, only for the Solidity contracts and the zero-knowledge circuit:

```bash
make foundry        # stable Foundry into .tools/foundry (project-local; never touches a global install)
make contract-test  # 47 Foundry tests
make circuit-test   # Noir circuit tests (needs nargo 1.0.0-beta.16 and bb 2.1.8 on PATH)
make difftest       # Python engine vs the Solidity contracts on a local Anvil chain
```

Without `.tools/` the EVM and ZK tests are skipped, and everything else runs.

## The dashboard (review day)
```bash
make dashboard      # opens http://localhost:8501
```

- **Offline.** The dashboard reads only precomputed results: `dashboard/data/` and the archives in `docs/report/`. The only live computation is the search tree in Act 4, which takes milliseconds.
- **Demo order.** The landing page walks the four acts: the market works → predators → the defense → search, then the verdicts.
- **Fallback.** If Streamlit fails on the review machine, every view's key figure is a PNG in `dashboard/fallback/`, numbered in demo order.
- **Rebuilding.** `make dashboard-data` rebuilds the data and the fallbacks deterministically from the committed configs (a few seconds).

## Running experiments
Each experiment is a YAML file in `sim/experiments/configs/`. Outputs go to `results/<name>/`, which is not committed. The archived copies used in the report are in `docs/report/`.

```bash
.venv/bin/python -m tfs run sim/experiments/configs/e2a.yaml   # an experiment (200 seeds)
.venv/bin/python -m tfs h3                                     # pre-registered H3 verdicts from E3 runs
.venv/bin/python -m tfs h4                                     # pre-registered H4 verdict from the E4 run
.venv/bin/python -m tfs shock-study sim/experiments/configs/shock_f.yaml
.venv/bin/python -m tfs e5 sim/experiments/configs/e5.yaml
.venv/bin/python -m tfs search-bench                           # pruning benchmark
.venv/bin/python -m tfs replay sim/experiments/configs/e2a.yaml --seed 3 --market 15   # explain a front-run
```

Every run is driven by a master seed, so the same command gives the same numbers. Each archived run records its commit in `meta.json`.

## Layout
| Path | What |
|---|---|
| `sim/tfs/` | the Python package: information model, agents, mempool, engines, search, experiments |
| `contracts/` | Solidity (Foundry): LMSR market, outcome shares, router, oracle, sealed batch auction, identity registry, verifier |
| `circuits/` | Noir: the `sealed_order` validity circuit and its shared hash library |
| `dashboard/` | review-day dashboard, its precomputed data and PNG fallbacks |
| `docs/` | specification, decisions, pre-registration, report and archived results |
| `tests/` | Python tests (unit, property-based, differential, dashboard smoke tests) |
