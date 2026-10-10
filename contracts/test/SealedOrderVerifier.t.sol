// SPDX-License-Identifier: MIT
pragma solidity 0.8.27;

import {Test} from "forge-std/Test.sol";
import {HonkVerifier} from "../src/SealedOrderVerifier.sol";

/// @notice The bb-generated UltraHonk verifier accepts a real sealed_order proof and rejects tampering.
/// Fixture: produced by tfs.zk.prover (order: buy 20 YES at <= 0.6, escrow 25 USDC, batch 7).
contract SealedOrderVerifierTest is Test {
    HonkVerifier verifier;
    bytes proof;
    bytes32[] inputs;

    function setUp() public {
        verifier = new HonkVerifier();
        string memory json = vm.readFile("test/fixtures/sealed_order_proof.json");
        proof = vm.parseJsonBytes(json, ".proof");
        inputs = vm.parseJsonBytes32Array(json, ".publicInputs");
    }

    function test_AcceptsValidProof() public {
        uint256 gasBefore = gasleft();
        bool ok = verifier.verify(proof, inputs);
        uint256 used = gasBefore - gasleft();
        assertTrue(ok);
        emit log_named_uint("verify gas", used);
    }

    function test_RejectsWrongEscrow() public {
        inputs[1] = bytes32(uint256(5_000_000)); // claim a smaller escrow than was proven
        vm.expectRevert();
        verifier.verify(proof, inputs);
    }

    function test_RejectsWrongBatch() public {
        inputs[2] = bytes32(uint256(8)); // replay the proof in another batch
        vm.expectRevert();
        verifier.verify(proof, inputs);
    }
}
