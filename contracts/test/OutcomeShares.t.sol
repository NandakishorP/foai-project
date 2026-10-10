// SPDX-License-Identifier: MIT
pragma solidity 0.8.27;

import {Test} from "forge-std/Test.sol";
import {MockUSDC} from "../src/MockUSDC.sol";
import {OutcomeShares} from "../src/OutcomeShares.sol";

contract OutcomeSharesTest is Test {
    MockUSDC usdc;
    OutcomeShares shares;
    address oracle = makeAddr("oracle");
    address alice = makeAddr("alice");
    address bob = makeAddr("bob");
    uint256 id;

    function setUp() public {
        usdc = new MockUSDC();
        shares = new OutcomeShares(usdc);
        id = shares.createMarket(oracle);
        for (uint256 i = 0; i < 2; i++) {
            address u = i == 0 ? alice : bob;
            usdc.mint(u, 1_000e6);
            vm.prank(u);
            usdc.approve(address(shares), type(uint256).max);
        }
    }

    function test_SplitAndMergeAreInverse() public {
        vm.startPrank(alice);
        shares.split(id, 10e6);
        assertEq(shares.balanceOf(alice, shares.tokenId(id, 0)), 10e6);
        assertEq(shares.balanceOf(alice, shares.tokenId(id, 1)), 10e6);
        assertEq(usdc.balanceOf(alice), 990e6);
        shares.merge(id, 4e6);
        vm.stopPrank();
        assertEq(usdc.balanceOf(alice), 994e6);
        assertEq(shares.collateralOf(id), 6e6);
    }

    function test_OnlyOracleResolves() public {
        vm.expectRevert(OutcomeShares.NotOracle.selector);
        shares.reportOutcome(id, 0);
        vm.prank(oracle);
        shares.reportOutcome(id, 1);
        vm.prank(oracle);
        vm.expectRevert(OutcomeShares.AlreadyResolved.selector);
        shares.reportOutcome(id, 0);
    }

    function test_RedeemPaysWinnersOnly() public {
        vm.prank(alice);
        shares.split(id, 10e6);
        // alice keeps YES, gives NO to bob (compute the id first: vm.prank applies to the next external call)
        uint256 noId = shares.tokenId(id, 1);
        vm.prank(alice);
        shares.safeTransferFrom(alice, bob, noId, 10e6, "");
        vm.prank(oracle);
        shares.reportOutcome(id, 1); // NO wins
        vm.prank(alice);
        assertEq(shares.redeem(id), 0);
        vm.prank(bob);
        assertEq(shares.redeem(id), 10e6);
        assertEq(usdc.balanceOf(bob), 1_010e6);
        assertEq(shares.collateralOf(id), 0);
        assertEq(shares.totalSupply(shares.tokenId(id, 0)), 0);
    }

    function test_RedeemBeforeResolutionReverts() public {
        vm.expectRevert(OutcomeShares.NotResolved.selector);
        shares.redeem(id);
    }

    function testFuzz_CollateralEqualsCompleteSets(uint96 a, uint96 b, uint96 m) public {
        uint256 x = bound(a, 0, 500e6);
        uint256 y = bound(b, 0, 500e6);
        vm.prank(alice);
        shares.split(id, x);
        vm.prank(bob);
        shares.split(id, y);
        uint256 mergeAmt = bound(m, 0, x);
        vm.prank(alice);
        shares.merge(id, mergeAmt);
        uint256 sets = shares.totalSupply(shares.tokenId(id, 0));
        assertEq(sets, shares.totalSupply(shares.tokenId(id, 1)));
        assertEq(shares.collateralOf(id), sets);
        assertEq(usdc.balanceOf(address(shares)), sets);
    }
}
