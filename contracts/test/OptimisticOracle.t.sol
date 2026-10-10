// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {Test} from "forge-std/Test.sol";
import {MockUSDC} from "../src/MockUSDC.sol";
import {OutcomeShares} from "../src/OutcomeShares.sol";
import {OptimisticOracle} from "../src/OptimisticOracle.sol";

contract OptimisticOracleTest is Test {
    MockUSDC usdc;
    OutcomeShares shares;
    OptimisticOracle oracle;
    address resolver = makeAddr("vote");
    address proposer = makeAddr("proposer");
    address disputer = makeAddr("disputer");
    uint256 id;
    uint256 constant BOND = 100e6;

    function setUp() public {
        usdc = new MockUSDC();
        shares = new OutcomeShares(usdc);
        oracle = new OptimisticOracle(usdc, shares, BOND, 1 hours, 1_000, resolver); // 10% burn
        id = shares.createMarket(address(oracle));
        for (uint256 i = 0; i < 2; i++) {
            address u = i == 0 ? proposer : disputer;
            usdc.mint(u, 1_000e6);
            vm.prank(u);
            usdc.approve(address(oracle), type(uint256).max);
        }
    }

    function test_UndisputedProposalSettlesAfterWindow() public {
        vm.prank(proposer);
        oracle.propose(id, 1);
        vm.expectRevert(OptimisticOracle.WindowOpen.selector);
        oracle.settle(id);
        vm.warp(block.timestamp + 1 hours);
        oracle.settle(id);
        (bool resolved, uint8 winner) = _market();
        assertTrue(resolved);
        assertEq(winner, 1);
        assertEq(usdc.balanceOf(proposer), 1_000e6); // bond returned
    }

    function test_DisputeAfterWindowIsTooLate() public {
        vm.prank(proposer);
        oracle.propose(id, 1);
        vm.warp(block.timestamp + 1 hours);
        vm.prank(disputer);
        vm.expectRevert(OptimisticOracle.WindowClosed.selector);
        oracle.dispute(id);
    }

    function test_FalseProposalLosesBondToDisputer() public {
        vm.prank(proposer);
        oracle.propose(id, 0); // false
        vm.prank(disputer);
        oracle.dispute(id);
        vm.prank(resolver);
        oracle.resolveDispute(id, 1); // the vote finds the truth
        assertEq(usdc.balanceOf(disputer), 1_000e6 + BOND - 10e6); // wins the proposer's bond minus 10% burn
        assertEq(usdc.balanceOf(proposer), 1_000e6 - BOND);
        assertEq(usdc.balanceOf(oracle.BURN()), 10e6);
        (, uint8 winner) = _market();
        assertEq(winner, 1);
    }

    function test_BadDisputeLosesBond() public {
        vm.prank(proposer);
        oracle.propose(id, 1);
        vm.prank(disputer);
        oracle.dispute(id);
        vm.prank(resolver);
        oracle.resolveDispute(id, 1);
        assertEq(usdc.balanceOf(proposer), 1_000e6 + BOND - 10e6);
        assertEq(usdc.balanceOf(disputer), 1_000e6 - BOND);
    }

    function test_OnlyResolverDecidesDisputes() public {
        vm.prank(proposer);
        oracle.propose(id, 1);
        vm.prank(disputer);
        oracle.dispute(id);
        vm.expectRevert(OptimisticOracle.OnlyResolver.selector);
        oracle.resolveDispute(id, 0);
    }

    function test_CannotProposeTwice() public {
        vm.prank(proposer);
        oracle.propose(id, 1);
        vm.prank(disputer);
        vm.expectRevert(OptimisticOracle.WrongStatus.selector);
        oracle.propose(id, 0);
    }

    function testFuzz_BondsAreConserved(bool honest, uint8 vote) public {
        uint8 truth = 1;
        vm.prank(proposer);
        oracle.propose(id, honest ? truth : 0);
        vm.prank(disputer);
        oracle.dispute(id);
        vm.prank(resolver);
        oracle.resolveDispute(id, vote % 2);
        uint256 total = usdc.balanceOf(proposer) + usdc.balanceOf(disputer) + usdc.balanceOf(oracle.BURN());
        assertEq(total, 2_000e6);
        assertEq(usdc.balanceOf(address(oracle)), 0);
    }

    function _market() internal view returns (bool resolved, uint8 winner) {
        (, resolved, winner) = shares.markets(id);
    }
}
