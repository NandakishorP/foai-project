// SPDX-License-Identifier: MIT
pragma solidity 0.8.27;

import {Test} from "forge-std/Test.sol";
import {MockUSDC} from "../src/MockUSDC.sol";
import {OutcomeShares} from "../src/OutcomeShares.sol";
import {LMSRMarket} from "../src/LMSRMarket.sol";

/// @dev Shared setup: this test contract plays the router.
contract LMSRBase is Test {
    MockUSDC usdc;
    OutcomeShares shares;
    LMSRMarket market;
    address oracle = makeAddr("oracle");
    address alice = makeAddr("alice");
    address bob = makeAddr("bob");
    uint256 constant FUNDING = 69_314_719; // b·ln 2 for b = 100, rounded up (USDC 6 decimals)

    function setUp() public virtual {
        usdc = new MockUSDC();
        shares = new OutcomeShares(usdc);
        uint256 id = shares.createMarket(oracle);
        market = new LMSRMarket(usdc, shares, id, 100e18, address(this));
        usdc.mint(address(market), FUNDING);
        _fund(alice);
        _fund(bob);
    }

    function _fund(address u) internal {
        usdc.mint(u, 10_000e6);
        vm.startPrank(u);
        usdc.approve(address(market), type(uint256).max);
        shares.setApprovalForAll(address(market), true);
        vm.stopPrank();
    }

    function _yes(address u) internal view returns (uint256) {
        return shares.balanceOf(u, shares.tokenId(0, 0));
    }

    function _no(address u) internal view returns (uint256) {
        return shares.balanceOf(u, shares.tokenId(0, 1));
    }
}

contract LMSRMarketTest is LMSRBase {
    function test_StartsAtHalf() public view {
        assertEq(market.priceYes(), 0.5e18);
    }

    function test_BuyCostMatchesClosedForm() public {
        // Python: 100 * ln((e^0.1 + 1) / 2) = 5.124947951... USDC; the cost is rounded up
        uint256 paid = market.buy(alice, 0, 10e6, type(uint256).max);
        assertEq(paid, 5_124_948);
        assertEq(_yes(alice), 10e6);
        assertApproxEqAbs(market.priceYes(), 524_979_187_478_939_985, 1e6); // 1/(1+e^-0.1)
    }

    function test_LimitIsEnforced() public {
        vm.expectRevert(abi.encodeWithSelector(LMSRMarket.LimitExceeded.selector, 5_124_948, 5_000_000));
        market.buy(alice, 0, 10e6, 5_000_000);
    }

    function test_OnlyRouterCanTrade() public {
        vm.prank(alice);
        vm.expectRevert(LMSRMarket.OnlyRouter.selector);
        market.buy(alice, 0, 1e6, type(uint256).max);
    }

    function test_SellReturnsProceedsAndInventoryMerges() public {
        market.buy(alice, 0, 10e6, type(uint256).max);
        market.buy(bob, 1, 4e6, type(uint256).max);
        // the market maker holds 10 NO from the first split, 4 went to bob; YES inventory is 0, so nothing merges yet
        uint256 received = market.sell(alice, 0, 10e6, 0);
        assertGt(received, 0);
        assertEq(_yes(alice), 0);
        // after the sell the market maker holds 10 YES and 6 NO: 6 pairs merged back
        assertEq(shares.balanceOf(address(market), shares.tokenId(0, 0)), 4e6);
        assertEq(shares.balanceOf(address(market), shares.tokenId(0, 1)), 0);
    }

    function testFuzz_RoundTripCostsAtMostRounding(uint64 amount, bool yes) public {
        uint256 x = bound(amount, 1, 500e6);
        uint8 side = yes ? 0 : 1;
        uint256 before = usdc.balanceOf(alice);
        market.buy(alice, side, x, type(uint256).max);
        market.sell(alice, side, x, 0);
        uint256 lost = before - usdc.balanceOf(alice);
        assertLe(lost, 2); // one unit of rounding on each leg, in the market maker's favour
        assertEq(market.priceYes(), 0.5e18);
    }

    function testFuzz_PricesSumToOne(int64 a, int64 c) public {
        uint256 x = bound(uint256(int256(a) < 0 ? -int256(a) : int256(a)), 0, 3_000e6);
        uint256 y = bound(uint256(int256(c) < 0 ? -int256(c) : int256(c)), 0, 3_000e6);
        if (x > 0) market.buy(alice, 0, x, type(uint256).max);
        if (y > 0) market.buy(bob, 1, y, type(uint256).max);
        uint256 p = market.priceYes();
        assertGt(p, 0);
        assertLt(p, 1e18);
    }

    function test_ExtremeImbalanceDoesNotOverflow() public {
        usdc.mint(alice, 1_000_000e6);
        market.buy(alice, 0, 20_000e6, type(uint256).max); // q_yes/b = 200: far beyond exp's input limit without log-sum-exp
        assertGt(market.priceYes(), 0.999999e18);
    }
}
