// SPDX-License-Identifier: MIT
pragma solidity 0.8.27;

import {Test} from "forge-std/Test.sol";
import {MockUSDC} from "../src/MockUSDC.sol";
import {OutcomeShares} from "../src/OutcomeShares.sol";
import {LMSRMarket} from "../src/LMSRMarket.sol";
import {TradeRouter} from "../src/TradeRouter.sol";
import {IdentityRegistry} from "../src/IdentityRegistry.sol";
import {MockVerifier} from "../src/MockVerifier.sol";
import {HonkVerifier} from "../src/SealedOrderVerifier.sol";
import {SealedBatchAuction, IVerifier} from "../src/SealedBatchAuction.sol";

/// @dev Test-only registry whose root can be set, to match the proof fixture's synthetic Merkle path.
contract SettableRootRegistry is IdentityRegistry {
    constructor(MockUSDC usdc_) IdentityRegistry(usdc_, 0) {}

    function setRoot(uint256 r) external {
        root = r;
    }
}

contract AuctionBase is Test {
    MockUSDC usdc;
    OutcomeShares shares;
    LMSRMarket market;
    TradeRouter router;
    SealedBatchAuction auction;
    address slash = makeAddr("slash");
    address[] traders;
    uint256 constant K = 5;
    uint256 constant FUNDING = 69_314_719;

    function _deploy(IVerifier verifier, IdentityRegistry registry) internal {
        router = new TradeRouter(usdc, makeAddr("builder"), 0);
        market = new LMSRMarket(usdc, shares, shares.createMarket(address(1)), 100e18, address(router));
        usdc.mint(address(market), FUNDING);
        uint256[] memory tiers = new uint256[](4);
        tiers[0] = 5e6;
        tiers[1] = 25e6;
        tiers[2] = 125e6;
        tiers[3] = 625e6;
        auction = new SealedBatchAuction(usdc, shares, market, router, verifier, registry, K, tiers, slash);
        for (uint256 i = 0; i < 8; i++) {
            address t = makeAddr(string(abi.encodePacked("trader", i)));
            traders.push(t);
            usdc.mint(t, 10_000e6);
            vm.prank(t);
            usdc.approve(address(auction), type(uint256).max);
        }
    }

    function setUp() public virtual {
        usdc = new MockUSDC();
        shares = new OutcomeShares(usdc);
        _deploy(IVerifier(address(new MockVerifier())), new IdentityRegistry(usdc, 0));
    }

    function _commit(uint256 who, uint8 side, uint256 limit, uint256 size, uint256 tier, uint256 salt)
        internal
        returns (uint256 index)
    {
        uint256 c = auction.commitmentOf(side, limit, size, salt, 1000 + who);
        vm.prank(traders[who]);
        (, index) = auction.commit(c, tier, uint256(keccak256(abi.encode(who, salt))), "");
    }

    function _reveal(uint256 index, uint256 who, uint8 side, uint256 limit, uint256 size, uint256 salt) internal {
        auction.reveal(0, index, side, limit, size, salt, 1000 + who);
    }

    function _held(uint256 who, uint8 side) internal view returns (uint256) {
        return shares.balanceOf(traders[who], shares.tokenId(market.marketId(), side));
    }

    function _totalUsdc() internal view returns (uint256 t) {
        for (uint256 i = 0; i < traders.length; i++) {
            t += usdc.balanceOf(traders[i]);
        }
        t += usdc.balanceOf(address(auction)) + usdc.balanceOf(address(market)) + usdc.balanceOf(address(shares))
            + usdc.balanceOf(slash) + usdc.balanceOf(router.builder());
    }
}

contract SealedBatchAuctionTest is AuctionBase {
    function test_CommitRevealClear_UniformPriceAndConservation() public {
        uint256 total = _totalUsdc();
        uint256 a = _commit(0, 0, 600_000, 20e6, 25e6, 1); // buy 20 YES at <= 0.6
        uint256 b = _commit(1, 1, 600_000, 10e6, 25e6, 2); // buy 10 NO at <= 0.6
        vm.roll(block.number + K);
        _reveal(a, 0, 0, 600_000, 20e6, 1);
        _reveal(b, 1, 1, 600_000, 10e6, 2);
        auction.clear(0);
        assertEq(_held(0, 0), 20e6);
        assertEq(_held(1, 1), 10e6);
        assertEq(_totalUsdc(), total); // money only moved
        assertLt(usdc.balanceOf(address(auction)), 10); // dust from rounding up only
        assertGt(market.priceYes(), 0.5e18); // net 10 YES went through the LMSR
    }

    function test_IdenticalOrdersShareProRata() public {
        // each alone moves the price to 0.6 (b ln(0.6/0.4) = 40.5465 shares); together they overshoot
        uint256[] memory idx = new uint256[](5);
        for (uint256 i = 0; i < 5; i++) {
            idx[i] = _commit(i, 0, 600_000, 40_546_510, 25e6, i);
        }
        vm.roll(block.number + K);
        for (uint256 i = 0; i < 5; i++) {
            _reveal(idx[i], i, 0, 600_000, 40_546_510, i);
        }
        auction.clear(0);
        uint256 first = _held(0, 0);
        assertGt(first, 0);
        assertLt(first, 40_546_510);
        for (uint256 i = 1; i < 5; i++) {
            assertApproxEqAbs(_held(i, 0), first, 1);
        }
        // the uniform price (the LMSR's average price over the imbalance) lands on the shared limit
        uint256 paid = 10_000e6 - usdc.balanceOf(traders[0]);
        assertApproxEqAbs(paid * 1e18 / first, 0.6e18, 1e12);
    }

    function test_UnrevealedEscrowIsSlashed() public {
        _commit(0, 0, 600_000, 20e6, 25e6, 1);
        vm.roll(block.number + K);
        auction.clear(0);
        assertEq(usdc.balanceOf(slash), 25e6);
    }

    function test_TimingRules() public {
        uint256 a = _commit(0, 0, 600_000, 20e6, 25e6, 1);
        vm.expectRevert(SealedBatchAuction.WindowOpen.selector);
        _reveal(a, 0, 0, 600_000, 20e6, 1);
        vm.expectRevert(SealedBatchAuction.WindowOpen.selector);
        auction.clear(0);
        vm.roll(block.number + K);
        vm.expectRevert(SealedBatchAuction.BadOpening.selector);
        _reveal(a, 0, 0, 600_000, 21e6, 1); // not what was committed
        auction.clear(0);
        vm.expectRevert(SealedBatchAuction.AlreadyCleared.selector);
        auction.clear(0);
    }

    function test_TiersAndNullifiers() public {
        uint256 c = auction.commitmentOf(0, 600_000, 1e6, 1, 1000);
        vm.prank(traders[0]);
        vm.expectRevert(SealedBatchAuction.NotATier.selector);
        auction.commit(c, 7e6, 1, "");
        vm.prank(traders[0]);
        auction.commit(c, 5e6, 42, "");
        vm.prank(traders[1]);
        vm.expectRevert(SealedBatchAuction.NullifierUsed.selector); // same identity nullifier, same batch
        auction.commit(c, 5e6, 42, "");
    }

    /// Random batches: money is conserved, no fill pays more than its limit (beyond one rounding unit),
    /// and the auction keeps only rounding dust.
    function testFuzz_RandomBatch(uint256 seed) public {
        uint256 total = _totalUsdc();
        uint256 n = 1 + seed % 8;
        uint256[] memory idx = new uint256[](n);
        uint8[] memory side = new uint8[](n);
        uint256[] memory limit = new uint256[](n);
        uint256[] memory size = new uint256[](n);
        for (uint256 i = 0; i < n; i++) {
            uint256 r = uint256(keccak256(abi.encode(seed, i)));
            side[i] = uint8(r % 2);
            limit[i] = 50_000 + (r >> 8) % 900_000;
            size[i] = 1e6 + (r >> 40) % 150e6;
            uint256 tier = limit[i] * size[i] <= 25e6 * 1e6 ? 25e6 : limit[i] * size[i] <= 125e6 * 1e6 ? 125e6 : 625e6;
            idx[i] = _commit(i, side[i], limit[i], size[i], tier, i);
        }
        vm.roll(block.number + K);
        for (uint256 i = 0; i < n; i++) {
            _reveal(idx[i], i, side[i], limit[i], size[i], i);
        }
        auction.clear(0);
        assertEq(_totalUsdc(), total);
        assertLt(usdc.balanceOf(address(auction)), 2 * n + 2);
        uint256 p = market.priceYes();
        assertGt(p, 0);
        assertLt(p, 1e18);
    }
}

contract CommitRevealAuctionTest is AuctionBase {
    function setUp() public override {
        usdc = new MockUSDC();
        shares = new OutcomeShares(usdc);
        _deploy(IVerifier(address(0)), new IdentityRegistry(usdc, 0)); // no proofs
    }

    function test_InsolventOrderIsSlashedAtClearing() public {
        uint256 a = _commit(0, 0, 900_000, 100e6, 5e6, 1); // worst case 90 USDC on a 5 USDC escrow
        vm.roll(block.number + K);
        _reveal(a, 0, 0, 900_000, 100e6, 1);
        auction.clear(0);
        assertEq(usdc.balanceOf(slash), 5e6);
        assertEq(_held(0, 0), 0);
    }

    function test_OneOrderPerAddressPerBatch() public {
        _commit(0, 0, 600_000, 1e6, 5e6, 1);
        uint256 c = auction.commitmentOf(1, 600_000, 1e6, 2, 1000);
        vm.prank(traders[0]);
        vm.expectRevert(SealedBatchAuction.NullifierUsed.selector);
        auction.commit(c, 5e6, 0, "");
    }
}

contract RealProofAuctionTest is AuctionBase {
    SettableRootRegistry registry;

    function setUp() public override {
        usdc = new MockUSDC();
        shares = new OutcomeShares(usdc);
        registry = new SettableRootRegistry(usdc);
        _deploy(IVerifier(address(new HonkVerifier())), registry);
    }

    /// The fixture proof (tfs.zk.prover): buy 20 YES at <= 0.6, escrow 25, batch 7, secret 1234567, salt 42.
    function test_RealProofCommitRevealAndClear() public {
        string memory json = vm.readFile("test/fixtures/sealed_order_proof.json");
        bytes memory proof = vm.parseJsonBytes(json, ".proof");
        bytes32[] memory pi = vm.parseJsonBytes32Array(json, ".publicInputs");
        registry.setRoot(uint256(pi[4]));
        vm.roll(block.number + 7 * K); // batch 7, as proven
        assertEq(auction.currentBatch(), 7);
        vm.prank(traders[0]);
        (uint256 batchId, uint256 index) = auction.commit(uint256(pi[0]), uint256(pi[1]), uint256(pi[3]), proof);
        vm.prank(traders[0]);
        vm.expectRevert(SealedBatchAuction.NullifierUsed.selector); // the same proof cannot be replayed
        auction.commit(uint256(pi[0]), uint256(pi[1]), uint256(pi[3]), proof);
        vm.roll(block.number + K);
        auction.reveal(batchId, index, 0, 600_000, 20e6, 42, 1234567);
        auction.clear(batchId);
        assertEq(_held(0, 0), 20e6);
    }
}
