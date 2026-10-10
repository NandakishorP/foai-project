// SPDX-License-Identifier: MIT
pragma solidity 0.8.27;

import {Test} from "forge-std/Test.sol";
import {StdInvariant} from "forge-std/StdInvariant.sol";
import {SD59x18, sd} from "@prb/math/src/SD59x18.sol";
import {MockUSDC} from "../../src/MockUSDC.sol";
import {OutcomeShares} from "../../src/OutcomeShares.sol";
import {LMSRMarket} from "../../src/LMSRMarket.sol";

/// @dev Random traffic: buys, sells, splits and merges by three actors. The handler is the market's router.
contract Handler is Test {
    MockUSDC public usdc;
    OutcomeShares public shares;
    LMSRMarket public market;
    address[3] public actors;

    constructor(MockUSDC usdc_, OutcomeShares shares_) {
        usdc = usdc_;
        shares = shares_;
    }

    function setMarket(LMSRMarket market_) external {
        market = market_;
        for (uint256 i = 0; i < 3; i++) {
            actors[i] = makeAddr(string(abi.encodePacked("actor", i)));
            usdc.mint(actors[i], 1_000_000e6);
            vm.startPrank(actors[i]);
            usdc.approve(address(market), type(uint256).max);
            usdc.approve(address(shares), type(uint256).max);
            shares.setApprovalForAll(address(market), true);
            vm.stopPrank();
        }
    }

    function buy(uint256 who, bool yes, uint256 amount) external {
        market.buy(actors[who % 3], yes ? 0 : 1, bound(amount, 1, 2_000e6), type(uint256).max);
    }

    function sell(uint256 who, bool yes, uint256 fraction) external {
        address a = actors[who % 3];
        uint8 side = yes ? 0 : 1;
        uint256 held = shares.balanceOf(a, shares.tokenId(0, side));
        uint256 amount = held * bound(fraction, 0, 100) / 100;
        if (amount > 0) market.sell(a, side, amount, 0);
    }

    function split(uint256 who, uint256 amount) external {
        vm.prank(actors[who % 3]);
        shares.split(0, bound(amount, 0, 1_000e6));
    }

    function merge(uint256 who, uint256 amount) external {
        address a = actors[who % 3];
        uint256 y = shares.balanceOf(a, shares.tokenId(0, 0));
        uint256 n = shares.balanceOf(a, shares.tokenId(0, 1));
        uint256 m = bound(amount, 0, y < n ? y : n);
        vm.prank(a);
        shares.merge(0, m);
    }
}

contract MarketInvariants is Test {
    MockUSDC usdc;
    OutcomeShares shares;
    LMSRMarket market;
    Handler handler;
    uint256 constant FUNDING = 69_314_719; // b·ln 2 for b = 100, rounded up

    function setUp() public {
        usdc = new MockUSDC();
        shares = new OutcomeShares(usdc);
        shares.createMarket(makeAddr("oracle"));
        handler = new Handler(usdc, shares);
        market = new LMSRMarket(usdc, shares, 0, 100e18, address(handler));
        handler.setMarket(market);
        usdc.mint(address(market), FUNDING);
        targetContract(address(handler));
        // fuzz only the four trading actions (not setMarket or helpers inherited from Test)
        bytes4[] memory actions = new bytes4[](4);
        actions[0] = Handler.buy.selector;
        actions[1] = Handler.sell.selector;
        actions[2] = Handler.split.selector;
        actions[3] = Handler.merge.selector;
        targetSelector(StdInvariant.FuzzSelector({addr: address(handler), selectors: actions}));
    }

    /// Collateral conservation (SPEC §4): USDC held by OutcomeShares == outstanding complete sets.
    function invariant_CollateralEqualsCompleteSets() public view {
        uint256 yesSupply = shares.totalSupply(shares.tokenId(0, 0));
        assertEq(yesSupply, shares.totalSupply(shares.tokenId(0, 1)));
        assertEq(shares.collateralOf(0), yesSupply);
        assertEq(usdc.balanceOf(address(shares)), yesSupply);
    }

    /// The market maker's bookkeeping matches what traders hold. Traders may also split/merge
    /// complete sets themselves, which adds equal YES and NO, so the check is on the difference:
    /// traders' (YES − NO) == q_yes − q_no.
    function invariant_QMatchesTraderHoldings() public view {
        uint256 yesId = shares.tokenId(0, 0);
        uint256 noId = shares.tokenId(0, 1);
        int256 tradersYes = int256(shares.totalSupply(yesId) - shares.balanceOf(address(market), yesId));
        int256 tradersNo = int256(shares.totalSupply(noId) - shares.balanceOf(address(market), noId));
        int256 q = (market.qYes().unwrap() - market.qNo().unwrap()) / 1e12;
        assertEq(tradersYes - tradersNo, q);
    }

    /// Solvency and the b·ln 2 loss bound. The market maker's USDC is at least what exact LMSR
    /// accounting gives (rounding only helps it): funding + C(q) − C(0) − max(q).
    /// Since C(q) ≥ max(q) and C(0) = b·ln 2 = funding, this is ≥ 0: it can always pay.
    function invariant_MarketMakerSolventWithinLossBound() public view {
        SD59x18 qy = market.qYes();
        SD59x18 qn = market.qNo();
        SD59x18 maxQ = qy > qn ? qy : qn;
        SD59x18 exact = sd(int256(FUNDING) * 1e12) + market.cost(qy, qn) - market.cost(sd(0), sd(0)) - maxQ;
        int256 held = int256(usdc.balanceOf(address(market))) * 1e12;
        assertGe(held + 1e12, exact.unwrap()); // one USDC unit of slack for the funding's own rounding
        assertGe(exact.unwrap(), -1e12);
    }

    function invariant_PriceIsAProbability() public view {
        uint256 p = market.priceYes();
        assertLe(p, 1e18);
    }
}
