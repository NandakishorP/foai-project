// SPDX-License-Identifier: MIT
pragma solidity 0.8.27;

import {Test} from "forge-std/Test.sol";
import {LibPoseidon2Yul} from "poseidon2-evm/bn254/yul/LibPoseidon2Yul.sol";
import {MockUSDC} from "../src/MockUSDC.sol";
import {IdentityRegistry} from "../src/IdentityRegistry.sol";

contract IdentityRegistryTest is Test {
    MockUSDC usdc;
    IdentityRegistry registry;
    address alice = makeAddr("alice");

    function setUp() public {
        usdc = new MockUSDC();
        registry = new IdentityRegistry(usdc, 10e6);
        usdc.mint(alice, 100e6);
        vm.prank(alice);
        usdc.approve(address(registry), type(uint256).max);
    }

    function test_RegisterLocksStakeAndRejectsDuplicates() public {
        vm.startPrank(alice);
        registry.register(LibPoseidon2Yul.hash_1(1));
        assertEq(usdc.balanceOf(address(registry)), 10e6);
        vm.expectRevert(IdentityRegistry.AlreadyRegistered.selector);
        registry.register(LibPoseidon2Yul.hash_1(1));
        vm.stopPrank();
    }

    /// The path the prover gets must hash back to the root, exactly as order_lib's merkle_root does.
    function test_PathRecomputesRoot() public {
        vm.startPrank(alice);
        for (uint256 i = 1; i <= 3; i++) {
            registry.register(LibPoseidon2Yul.hash_1(i));
        }
        vm.stopPrank();
        for (uint256 index = 0; index < 3; index++) {
            (uint256[8] memory siblings, uint8[8] memory bits) = registry.path(index);
            uint256 node = registry.leaves(index);
            for (uint256 d = 0; d < 8; d++) {
                node = bits[d] == 0 ? LibPoseidon2Yul.hash_2(node, siblings[d]) : LibPoseidon2Yul.hash_2(siblings[d], node);
            }
            assertEq(node, registry.root());
        }
    }
}
