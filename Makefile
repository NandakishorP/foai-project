# Common commands. Foundry is the project-local stable install (DECISIONS D-030),
# never the global ~/.foundry (foundry-zksync, used by another project).

FOUNDRY_BIN := $(CURDIR)/.tools/foundry/bin
FORGE := $(FOUNDRY_BIN)/forge
ANVIL := $(FOUNDRY_BIN)/anvil
CAST  := $(FOUNDRY_BIN)/cast
PY    := .venv/bin/python

.PHONY: help foundry foundry-version test e1 season contracts contract-test difftest

help:
	@echo "make foundry          install stable Foundry into .tools/foundry (project-local)"
	@echo "make foundry-version  show which forge/anvil/cast this project uses"
	@echo "make test             run the Python test suite"
	@echo "make e1 | season      run experiment E1 / the season baseline"
	@echo "make contract-test    forge unit + invariant tests (project-local Foundry)"
	@echo "make difftest         FastEngine vs EvmEngine on all three scenarios (writes results/difftest/report.txt)"

foundry:
	./scripts/install_foundry.sh

foundry-version:
	@$(FORGE) --version | head -1
	@$(ANVIL) --version | head -1
	@$(CAST) --version | head -1

test:
	.venv/bin/pytest -q

e1:
	$(PY) -m tfs run sim/experiments/configs/e1.yaml

season:
	$(PY) -m tfs run sim/experiments/configs/season_baseline.yaml

contracts:
	cd contracts && $(FORGE) build

contract-test:
	cd contracts && $(FORGE) test

difftest:
	$(PY) -c "from pathlib import Path; from tfs.engines.differential import run_scenarios; [print(r.summary()) for r in run_scenarios(Path('results/difftest'))]"
