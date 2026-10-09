# Truth for Sale

An adversarial multi-agent simulation of an on-chain prediction market. Informed AI forecasters trade on private information; predator agents watch the mempool, infer who is informed, and front-run them. We measure how much "truth" the market loses, then deploy a ZK sealed-order batch auction as a defense and measure how much is restored.

**The full design is in `docs/SPEC.md`. Read it before starting any phase. It is the source of truth.**

## Context
- This is an AI course project (multi-agent systems, Topic 6: competitive financial market simulation). It is graded on a working implementation, a live code review, and a written report.
- The owner will be questioned on this code in a review. Code must be **readable and explainable**: clear names, short functions, docstrings explaining *why*, no clever tricks without a comment.
- Every agent must have a PEAS description in its class docstring (Performance, Environment, Actuators, Sensors).
- Course concepts must stay visible in the code: belief states (Bayesian updating), utility-based decisions (Kelly), search, and adversarial search (expectiminimax + alpha-beta — the order-splitting game in SPEC §6.1 is the headline; the oracle game is secondary).

## Scientific honesty (non-negotiable)
- The project tests hypotheses H1–H3 (SPEC top). **Never tune parameters, seeds, or agent logic to make a hypothesis come out true.** If results contradict a hypothesis, report it.
- Hypothesis verdict criteria are pre-registered in `docs/PREREGISTRATION.md` and committed before the experiment runs; never edit them after seeing results (log any change in `docs/DECISIONS.md`).
- Parameter values come from configs with a stated rationale; when sweeping, report the whole sweep, not the best point.
- The ZK defense's costs (SPEC §5.1) must always be measured and shown alongside its benefits.
- Polymarket is used for calibration only; never claim Polymarket itself is front-run via a mempool (SPEC §8).

## How to work
- **Build one phase at a time** (SPEC §11). Do not start a later phase's work unless asked.
- Start each phase in plan mode: propose the plan, file list, and tests; wait for approval before writing code.
- Finish each phase with its milestone demonstrated (a script or plot that shows it), all tests passing, and a short summary of what was built.
- If the spec is ambiguous or seems wrong, **ask** — do not silently change the design. Record agreed changes in `docs/DECISIONS.md` (date, decision, reason).
- Commit at each meaningful step with a clear message.

## Conventions
- **Python** (`sim/`, package name `tfs`): Python 3.12, type hints everywhere, dataclasses for state, `pytest` for tests. No global state.
- **Determinism:** every run is driven by a single master seed; use `numpy.random.Generator` passed explicitly. Same seed → identical results.
- **Config-driven:** experiments are YAML files in `sim/experiments/configs/`; no magic numbers buried in code.
- **Two engines, one interface:** `FastEngine` (pure Python) and `EvmEngine` (Anvil) must implement the same `Engine` interface. A differential test must prove they agree.
- **Solidity** (`contracts/`): Foundry, Solidity 0.8.x, OpenZeppelin, PRBMath for fixed-point. Unit tests + invariant tests for every contract.
- **Noir** (`circuits/`): Noir + Barretenberg (UltraHonk). Circuit tests for valid and invalid inputs.
- Anvil runs with automine **off**; blocks are mined explicitly by the builder.
- Keep dependencies minimal; add new ones only with a reason in `docs/DECISIONS.md`.

## Commands (fill in as the project grows)
- Python env (once): `uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -e ".[dev]"`
- Python tests: `.venv/bin/pytest -q`
- Run an experiment: `.venv/bin/python -m tfs run sim/experiments/configs/e1.yaml` (outputs in `results/<name>/`)
- One market plot: `.venv/bin/python -m tfs plot-market sim/experiments/configs/base.yaml --seed 1`
- Cost calibration: `.venv/bin/python -m tfs calibrate-costs sim/experiments/configs/calibrate_costs.yaml`
- Contract tests: `cd contracts && forge test`
- Circuit tests: `cd circuits/sealed_order && nargo test`
- Dashboard: `streamlit run dashboard/app.py`

## Non-goals
No real-money trading. No mainnet or testnet deployment.