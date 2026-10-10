"""Running a local Anvil chain and loading compiled contracts (Phase 2b).

Uses the project-local stable Foundry (`.tools/foundry/bin`, DECISIONS D-031), never the
global install. Anvil is started with:
- no automatic mining, so blocks are mined explicitly by the builder (CLAUDE.md);
- FIFO ordering, so a block contains transactions in exactly the order they were sent,
  which is the builder's order;
- zero gas prices, so ETH gas never matters. Fees in this project are USDC, paid through
  the TradeRouter.
"""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
FOUNDRY_BIN = ROOT / ".tools" / "foundry" / "bin"
CONTRACTS = ROOT / "contracts"


class AnvilUnavailable(RuntimeError):
    """The project-local Foundry is not installed (run `make foundry`)."""


def foundry_tool(name: str) -> Path:
    path = FOUNDRY_BIN / name
    if not path.exists():
        raise AnvilUnavailable(f"{path} not found; run `make foundry`")
    return path


def anvil_available() -> bool:
    return (FOUNDRY_BIN / "anvil").exists() and (FOUNDRY_BIN / "forge").exists()


def build_contracts() -> None:
    """Compile the contracts with the project-local forge (skipped if artifacts are up to date)."""
    subprocess.run([str(foundry_tool("forge")), "build", "--quiet"], cwd=CONTRACTS, check=True)


def load_artifact(name: str, source: str | None = None) -> tuple[list[Any], str]:
    """ABI and creation bytecode of contract `name` (declared in `source`.sol, default `name`.sol) from contracts/out."""
    data = _artifact(name, source)
    return data["abi"], data["bytecode"]["object"]


def link_references(name: str, source: str | None = None) -> list[tuple[str, str]]:
    """(source file, library name) pairs that must be deployed and linked into this contract's bytecode."""
    refs = _artifact(name, source)["bytecode"].get("linkReferences", {})
    return [(file, lib) for file, libs in refs.items() for lib in libs]


def link_placeholder(file: str, lib: str) -> str:
    """Solidity's placeholder for an unlinked library: __$ + first 34 hex chars of keccak256("file:lib") + $__."""
    from web3 import Web3

    return "__$" + Web3.keccak(text=f"{file}:{lib}").hex().removeprefix("0x")[:34] + "$__"


def _artifact(name: str, source: str | None) -> dict[str, Any]:
    path = CONTRACTS / "out" / f"{source or name}.sol" / f"{name}.json"
    if not path.exists():
        build_contracts()
    return json.loads(path.read_text())


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@dataclass
class AnvilProcess:
    """A private Anvil instance on a free port; stop() kills it."""

    accounts: int
    port: int = 0
    process: subprocess.Popen[bytes] | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> AnvilProcess:
        self.port = self.port or _free_port()
        args = [
            str(foundry_tool("anvil")),
            "--port", str(self.port),
            "--accounts", str(self.accounts),
            "--balance", "1000000",
            "--no-mining",            # blocks only when the builder says so
            "--order", "fifo",        # block order = send order
            "--gas-price", "0",
            "--base-fee", "0",
            "--gas-limit", "1000000000",  # room for a whole simulated block of trades
            "--silent",
        ]
        self.process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=0.2):
                    return self
            except OSError:
                time.sleep(0.05)
        self.stop()
        raise RuntimeError("anvil did not start")

    def stop(self) -> None:
        if self.process is not None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.process = None


def which_global_forge() -> str | None:
    """For diagnostics only: the global forge (foundry-zksync on this machine) is never used."""
    return shutil.which("forge")
