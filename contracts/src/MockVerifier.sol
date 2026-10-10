// SPDX-License-Identifier: MIT
pragma solidity 0.8.27;

/// @title MockVerifier
/// @notice TEST ONLY: accepts every proof. Used by the batch differential test to check clearing
/// and settlement maths over many orders without generating a real proof for each. The real
/// UltraHonk verifier (SealedOrderVerifier.sol) is exercised by its own tests and by the
/// real-proof integration test.
contract MockVerifier {
    function verify(bytes calldata, bytes32[] calldata) external pure returns (bool) {
        return true;
    }
}
