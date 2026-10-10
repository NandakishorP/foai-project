"""A real sealed_order proof, end to end on Anvil (Phase 3a): register an identity in the on-chain
registry, take the Merkle path from the registry, prove with Noir/bb, commit through the real
UltraHonk verifier, reveal, clear."""

import pytest

from tfs.core.types import Side, Venue
from tfs.engines.anvil import anvil_available
from tfs.zk.prover import SealedOrderSecret, public_values, prove, tools_available

pytestmark = [
    pytest.mark.evm,
    pytest.mark.skipif(not (anvil_available() and tools_available()), reason="needs .tools Foundry, nargo and bb"),
]
pytest.importorskip("web3")

from tfs.engines.evm import EvmEngine  # noqa: E402


def test_real_proof_through_registry_verifier_and_auction() -> None:
    with EvmEngine({Venue.MAIN: 100.0}, {"alice": 100.0, "bob": 100.0}) as e:
        e.enable_batches(5, [5.0, 25.0, 125.0, 625.0], verifier_kind="real")
        alice = e.address["alice"]
        secret = 777_001
        # 1. register alice's identity leaf (Poseidon2(secret), computed by the order_hasher circuit)
        dummy = SealedOrderSecret(0, 1, 1, 0, secret, 0, (0,) * 8, (0,) * 8)
        leaf = public_values(dummy).identity_leaf
        e._check(e._mined([e._send(e.registry.functions.register(leaf), alice)]), "register")
        other = public_values(SealedOrderSecret(0, 1, 1, 0, 888_002, 0, (0,) * 8, (0,) * 8)).identity_leaf
        e._check(e._mined([e._send(e.registry.functions.register(other), e.address["bob"])]), "register bob")
        # 2. the registry tells the prover where alice sits in the tree
        siblings, bits = e.registry.functions.path(0).call()
        batch_id = e.auction.functions.currentBatch().call()
        order = SealedOrderSecret(0, 600_000, 20_000_000, 42, secret, batch_id, tuple(siblings), tuple(bits))
        pv = public_values(order)
        assert pv.identity_root == e.registry.functions.root().call()  # Noir's root == the contract's root
        proof = prove(order, 25_000_000, pv.identity_root)
        # 3. commit with the proof (verified on-chain), then reveal and clear after the window
        commit = e._send(e.auction.functions.commit(pv.commitment, 25_000_000, pv.nullifier, proof.proof), alice)
        [receipt] = e._mined([commit])
        assert receipt.status == 1
        replay = e._send(e.auction.functions.commit(pv.commitment, 25_000_000, pv.nullifier, proof.proof), alice)
        assert e._mined([replay])[0].status == 0  # the nullifier stops a second order from the same identity
        end = e.auction.functions.windowEnd(batch_id).call()
        while e.w3.eth.block_number + 1 < end:
            e._mine()
        txs = [e._send(e.auction.functions.reveal(batch_id, 0, 0, 600_000, 20_000_000, 42, secret), alice),
               e._send(e.auction.functions.clear(batch_id), e.deployer)]
        assert all(r.status == 1 for r in e._mined(txs))
        assert e.balances()["alice"].position(Venue.MAIN, Side.YES) == 20.0
