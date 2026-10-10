// SPDX-License-Identifier: MIT
pragma solidity 0.8.27;

import {Test} from "forge-std/Test.sol";
import {LibPoseidon2} from "poseidon2-evm/bn254/solidity/LibPoseidon2.sol";
import {Field} from "poseidon2-evm/bn254/solidity/Field.sol";
import {LibPoseidon2Yul} from "poseidon2-evm/bn254/yul/LibPoseidon2Yul.sol";

/// @notice The on-chain Poseidon2 must equal Noir's (noir-lang/poseidon v0.1.1, used by the sealed_order circuit),
/// or reveals could never be checked against the commitments proven in the circuit. Vectors were printed by
/// `nargo test` with Poseidon2::hash([7],1), ([1,2],2) and ([1,2,3,4,5],5).
contract Poseidon2CompatTest is Test {
    function _hash(uint256[] memory xs) internal pure returns (uint256) {
        Field.Type[] memory inputs = new Field.Type[](xs.length);
        for (uint256 i = 0; i < xs.length; i++) {
            inputs[i] = Field.Type.wrap(xs[i]);
        }
        return Field.Type.unwrap(LibPoseidon2.hash(inputs, xs.length, false));
    }

    function test_MatchesNoirVectors() public pure {
        uint256[] memory one = new uint256[](1);
        one[0] = 7;
        assertEq(_hash(one), 0x29f0f539ca2b1865fb736203c036100998291b6e1072323a1db5022f0a52b3cc);

        uint256[] memory two = new uint256[](2);
        two[0] = 1;
        two[1] = 2;
        assertEq(_hash(two), 0x038682aa1cb5ae4e0a3f13da432a95c77c5c111f6f030faf9cad641ce1ed7383);

        uint256[] memory five = new uint256[](5);
        for (uint256 i = 0; i < 5; i++) {
            five[i] = i + 1;
        }
        assertEq(_hash(five), 0x2247be7014a54d17342a7ef677f58d28877780d203860396967f5d0a18d259db);
    }

    /// The cheaper Yul variant (used for the identity Merkle tree) must agree too.
    function test_YulVariantMatchesNoirVectors() public pure {
        assertEq(LibPoseidon2Yul.hash_1(7), 0x29f0f539ca2b1865fb736203c036100998291b6e1072323a1db5022f0a52b3cc);
        assertEq(LibPoseidon2Yul.hash_2(1, 2), 0x038682aa1cb5ae4e0a3f13da432a95c77c5c111f6f030faf9cad641ce1ed7383);
    }
}
