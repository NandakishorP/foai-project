// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {Test} from "forge-std/Test.sol";
import {MockUSDC} from "../src/MockUSDC.sol";
import {OutcomeShares} from "../src/OutcomeShares.sol";
import {LMSRMarket} from "../src/LMSRMarket.sol";
import {TradeRouter} from "../src/TradeRouter.sol";

contract TradeRouterTest is Test {
    MockUSDC usdc;
    OutcomeShares shares;
    LMSRMarket main;
    LMSRMarket ref;
    TradeRouter router;
    address builder = makeAddr("builder");
    address alice = makeAddr("alice");

    function setUp() public {
        usdc = new MockUSDC();
        shares = new OutcomeShares(usdc);
        router = new TradeRouter(usdc, builder, 10_000); // base fee 0.01 USDC
        main = new LMSRMarket(usdc, shares, shares.createMarket(address(1)), 100e18, address(router));
        ref = new LMSRMarket(usdc, shares, shares.createMarket(address(1)), 30e18, address(router));
        usdc.mint(address(main), 69_314_719);
        usdc.mint(address(ref), 20_794_416);
        usdc.mint(alice, 1_000e6);
        vm.startPrank(alice);
        usdc.approve(address(router), type(uint256).max);
        usdc.approve(address(main), type(uint256).max);
        usdc.approve(address(ref), type(uint256).max);
        shares.setApprovalForAll(address(main), true);
        shares.setApprovalForAll(address(ref), true);
        vm.stopPrank();
    }

    function _order(LMSRMarket m, uint8 side, int256 amount, uint256 limit, uint256 tip, bool protect)
        internal
        pure
        returns (TradeRouter.Order memory)
    {
        return TradeRouter.Order(m, side, amount, limit, tip, protect);
    }

    function test_FillPaysFeeAndTip() public {
        vm.prank(alice);
        assertTrue(router.execute(_order(main, 0, 10e6, 1e18, 50_000, false)));
        assertEq(usdc.balanceOf(builder), 60_000);
        assertEq(shares.balanceOf(alice, shares.tokenId(0, 0)), 10e6);
    }

    function test_FailedPlainOrderStillPaysFee() public {
        uint256 before = usdc.balanceOf(alice);
        vm.prank(alice);
        assertFalse(router.execute(_order(main, 0, 10e6, 0.5e18, 50_000, false))); // avg ~0.5125 > 0.5
        assertEq(usdc.balanceOf(builder), 60_000);
        assertEq(before - usdc.balanceOf(alice), 60_000);
        assertEq(main.priceYes(), 0.5e18);
    }

    function test_ProtectedOrderThatFailsPaysNothing() public {
        vm.prank(alice);
        vm.expectRevert();
        router.execute(_order(main, 0, 10e6, 0.5e18, 50_000, true));
        assertEq(usdc.balanceOf(builder), 0);
    }

    function test_SellWithLimit() public {
        vm.startPrank(alice);
        router.execute(_order(main, 0, 10e6, 1e18, 0, false));
        assertFalse(router.execute(_order(main, 0, -10e6, 0.9e18, 0, false))); // proceeds ~0.5125/share < 0.9
        assertTrue(router.execute(_order(main, 0, -10e6, 0.5e18, 0, false)));
        vm.stopPrank();
        assertEq(shares.balanceOf(alice, shares.tokenId(0, 0)), 0);
    }

    function test_BundleIsAllOrNothing() public {
        TradeRouter.Order[] memory legs = new TradeRouter.Order[](2);
        legs[0] = _order(ref, 0, 5e6, 1e18, 0, false);
        legs[1] = _order(main, 1, 5e6, 0.01e18, 0, false); // cannot fill at 1 cent
        uint256 before = usdc.balanceOf(alice);
        vm.prank(alice);
        vm.expectRevert();
        router.executeBundle(legs);
        assertEq(usdc.balanceOf(alice), before);
        assertEq(ref.priceYes(), 0.5e18);

        legs[1] = _order(main, 1, 5e6, 1e18, 0, false);
        vm.prank(alice);
        router.executeBundle(legs);
        assertEq(usdc.balanceOf(builder), 20_000); // base fee for each leg
    }

    function test_TradeForIsInternalOnly() public {
        vm.expectRevert(TradeRouter.OnlySelf.selector);
        router.tradeFor(alice, _order(main, 0, 1e6, 1e18, 0, false));
    }

    function test_CannotTradeWithSomeoneElsesApprovals() public {
        address mallory = makeAddr("mallory");
        vm.prank(mallory);
        vm.expectRevert(); // mallory cannot even pay the base fee: not included (FastEngine: "insufficient cash for fee")
        router.execute(_order(main, 0, 1e6, 1e18, 0, false));
        // the router always trades as msg.sender, so alice's approvals are never usable by mallory
        assertEq(shares.balanceOf(alice, shares.tokenId(0, 0)), 0);
        assertEq(usdc.balanceOf(alice), 1_000e6);
    }
}
