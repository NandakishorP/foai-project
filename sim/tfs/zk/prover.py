"""Generating real sealed_order proofs from Python (on-chain integration tests and the proving benchmark).

Public values (commitment, nullifier, identity leaf, Merkle root) come from the
`order_hasher` helper circuit, which uses the same Noir functions as `sealed_order`
(`circuits/order_lib`). Python never re-implements Poseidon2. The proof is an UltraHonk
proof from Barretenberg with the keccak transcript the generated Solidity verifier expects.

Both tools are the globally installed nargo 1.0.0-beta.16 and bb v2.1.8, which were
checked to be compatible (D-048). Each call runs in a unique Prover file, so calls do not interfere.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CIRCUITS = ROOT / "circuits"
DEPTH = 8
PRICE_ONE = 1_000_000


class ZkToolsUnavailable(RuntimeError):
    """nargo or bb not found on PATH."""


def tools_available() -> bool:
    return shutil.which("nargo") is not None and shutil.which("bb") is not None


@dataclass(frozen=True)
class SealedOrderSecret:
    """Everything the trader keeps private, plus where its identity sits in the registry tree."""

    side: int  # 0 = YES, 1 = NO
    limit: int  # millionths of 1 USDC per share, 0 < limit < 1_000_000
    size: int  # 6-decimal share units
    salt: int
    trader_secret: int
    batch_id: int
    path: tuple[int, ...]  # Merkle siblings, length DEPTH
    index_bits: tuple[int, ...]  # 0 = we are the left child, length DEPTH


@dataclass(frozen=True)
class PublicValues:
    commitment: int
    nullifier: int
    identity_leaf: int
    identity_root: int


def _toml(values: dict[str, object]) -> str:
    lines = []
    for key, value in values.items():
        if isinstance(value, (list, tuple)):
            lines.append(f"{key} = [{', '.join(repr(str(v)) for v in value)}]".replace("'", '"'))
        else:
            lines.append(f'{key} = "{value}"')
    return "\n".join(lines) + "\n"


def _run(args: list[str], cwd: Path) -> str:
    if not tools_available():
        raise ZkToolsUnavailable("nargo/bb not found")
    done = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if done.returncode != 0:
        raise RuntimeError(f"{' '.join(args)} failed:\n{done.stdout}\n{done.stderr}")
    return done.stdout + done.stderr


def public_values(o: SealedOrderSecret) -> PublicValues:
    """Commitment, nullifier, identity leaf and root, computed by the order_hasher circuit."""
    name = f"Prover_{uuid.uuid4().hex[:12]}"
    pkg = CIRCUITS / "order_hasher"
    (pkg / f"{name}.toml").write_text(_toml({
        "side": o.side, "limit": o.limit, "size": o.size, "salt": o.salt, "trader_secret": o.trader_secret,
        "batch_id": o.batch_id, "path": o.path, "index_bits": o.index_bits,
    }))
    try:
        out = _run(["nargo", "execute", "--prover-name", name, name], pkg)
    finally:
        (pkg / f"{name}.toml").unlink(missing_ok=True)
        (pkg / "target" / f"{name}.gz").unlink(missing_ok=True)
    values = [int(h, 16) for h in re.findall(r"0x[0-9a-fA-F]+", out.split("Circuit output:")[-1])]
    return PublicValues(*values)


@dataclass(frozen=True)
class Proof:
    proof: bytes
    public_inputs: list[int]  # commitment, escrow, batch_id, nullifier, identity_root
    seconds: float  # witness generation + proving, wall clock


def prove(o: SealedOrderSecret, escrow: int, identity_root: int) -> Proof:
    """Witness + UltraHonk proof (keccak transcript, for the EVM verifier)."""
    pv = public_values(o)
    name = f"Prover_{uuid.uuid4().hex[:12]}"
    pkg = CIRCUITS / "sealed_order"
    (pkg / f"{name}.toml").write_text(_toml({
        "side": o.side, "limit": o.limit, "size": o.size, "salt": o.salt, "trader_secret": o.trader_secret,
        "path": o.path, "index_bits": o.index_bits, "commitment": hex(pv.commitment), "escrow": escrow,
        "batch_id": o.batch_id, "nullifier": hex(pv.nullifier), "identity_root": hex(identity_root),
    }))
    out_dir = pkg / "target" / name
    try:
        _run(["nargo", "compile"], pkg)  # no-op when up to date
        _ensure_vk(pkg)
        start = time.perf_counter()
        _run(["nargo", "execute", "--prover-name", name, name], pkg)
        _run(["bb", "prove", "-b", "target/sealed_order.json", "-w", f"target/{name}.gz", "-o", str(out_dir),
              "-k", "target/vk", "--oracle_hash", "keccak"], pkg)
        seconds = time.perf_counter() - start
        proof = (out_dir / "proof").read_bytes()
        raw = (out_dir / "public_inputs").read_bytes()
        inputs = [int.from_bytes(raw[i:i + 32], "big") for i in range(0, len(raw), 32)]
    finally:
        (pkg / f"{name}.toml").unlink(missing_ok=True)
        (pkg / "target" / f"{name}.gz").unlink(missing_ok=True)
        shutil.rmtree(out_dir, ignore_errors=True)
    return Proof(proof, inputs, seconds)


def _ensure_vk(pkg: Path) -> None:
    """The verification key depends only on the compiled circuit: write it once, refresh when the circuit changes."""
    vk, circuit = pkg / "target" / "vk", pkg / "target" / "sealed_order.json"
    if not vk.exists() or vk.stat().st_mtime < circuit.stat().st_mtime:
        _run(["bb", "write_vk", "-b", "target/sealed_order.json", "-o", "target", "--oracle_hash", "keccak"], pkg)


def write_verification_key_and_verifier(solidity_out: Path) -> None:
    """Generate the verification key and the Solidity UltraHonk verifier for sealed_order."""
    pkg = CIRCUITS / "sealed_order"
    _run(["nargo", "compile"], pkg)
    _run(["bb", "write_vk", "-b", "target/sealed_order.json", "-o", "target", "--oracle_hash", "keccak"], pkg)
    _run(["bb", "write_solidity_verifier", "-k", "target/vk", "-o", str(solidity_out)], pkg)
