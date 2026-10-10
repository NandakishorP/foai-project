// SPDX-License-Identifier: MIT
pragma solidity 0.8.27;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {ERC1155Holder} from "@openzeppelin/contracts/token/ERC1155/utils/ERC1155Holder.sol";
import {SD59x18, sd} from "@prb/math/src/SD59x18.sol";
import {LibPoseidon2} from "poseidon2-evm/bn254/solidity/LibPoseidon2.sol";
import {Field} from "poseidon2-evm/bn254/solidity/Field.sol";
import {OutcomeShares} from "./OutcomeShares.sol";
import {LMSRMarket} from "./LMSRMarket.sol";
import {TradeRouter} from "./TradeRouter.sol";
import {IdentityRegistry} from "./IdentityRegistry.sol";

interface IVerifier {
    function verify(bytes calldata proof, bytes32[] calldata publicInputs) external returns (bool);
}

/// @title SealedBatchAuction
/// @notice Sealed buy orders for one market, cleared in batches at one uniform price (SPEC §5, D-046).
///
/// Per batch (K blocks of commit window, then reveal and clear):
///   1. commit: post a Poseidon2 commitment and a fixed escrow tier. With a verifier (ZK_BATCH)
///      a sealed_order proof shows the order is valid, solvent and from a registered identity,
///      with a per-identity nullifier. Without one (COMMIT_REVEAL) the nullifier is public:
///      one order per address per batch.
///   2. reveal: open the commitment. An order whose worst case exceeds its escrow is insolvent
///      (only possible without the proof).
///   3. clear: the uniform-price, pro-rata-margin rule, the same price-ladder algorithm as the
///      Python mirror (sim/tfs/market/batch.py), in 18-decimal fixed point. Matched YES/NO pairs
///      become complete sets (split); only the net imbalance trades with the LMSR, through the
///      TradeRouter. Fills pay the uniform price from their escrow and get the rest back.
///      Unrevealed and insolvent escrow goes to `slashSink`.
///
/// Units: limits in millionths (as in the circuit), sizes and USDC in 6 decimals, prices in 18 decimals.
contract SealedBatchAuction is ERC1155Holder {
    using SafeERC20 for IERC20;

    uint8 public constant YES = 0;
    uint8 public constant NO = 1;
    uint256 private constant ONE = 1e18;
    int256 private constant UNIT_TO_WAD = 1e12; // 6-decimal units -> 18-decimal fixed point
    uint256 private constant BISECTION_STEPS = 64;

    struct Sealed {
        address owner;
        uint256 commitment;
        uint256 escrow;
        bool revealed;
        uint8 side;
        uint256 limit; // millionths
        uint256 size; // 6 decimals
    }

    struct Fill {
        uint256 index; // into the batch's Sealed[]
        uint256 bound; // YES-price bound, 18 decimals
        bool yes;
        uint256 size;
        uint256 filled;
    }

    IERC20 public immutable usdc;
    OutcomeShares public immutable shares;
    LMSRMarket public immutable market;
    TradeRouter public immutable router;
    IVerifier public immutable verifier; // address(0): commit-reveal without proofs
    IdentityRegistry public immutable registry;
    uint256 public immutable marketId;
    uint256 public immutable startBlock;
    uint256 public immutable batchInterval;
    address public immutable slashSink;

    mapping(uint256 => Sealed[]) internal batches;
    mapping(uint256 => bool) public nullifierUsed;
    mapping(uint256 => bool) public cleared;
    mapping(uint256 => bool) public isTier;

    event Committed(uint256 indexed batchId, uint256 index, address indexed sender, uint256 escrow);
    event Revealed(uint256 indexed batchId, uint256 index, uint8 side, uint256 limit, uint256 size, bool solvent);
    event Cleared(uint256 indexed batchId, uint256 priceYes, int256 netYes, uint256 sets);
    event Filled(uint256 indexed batchId, uint256 index, address indexed owner, uint8 side, uint256 filled, uint256 paid);

    error NotATier();
    error NullifierUsed();
    error InvalidProof();
    error WindowOpen();
    error WindowClosed();
    error AlreadyCleared();
    error AlreadyRevealed();
    error BadOpening();

    constructor(
        IERC20 usdc_,
        OutcomeShares shares_,
        LMSRMarket market_,
        TradeRouter router_,
        IVerifier verifier_,
        IdentityRegistry registry_,
        uint256 batchInterval_,
        uint256[] memory tiers,
        address slashSink_
    ) {
        usdc = usdc_;
        shares = shares_;
        market = market_;
        router = router_;
        verifier = verifier_;
        registry = registry_;
        marketId = market_.marketId();
        startBlock = block.number;
        batchInterval = batchInterval_;
        slashSink = slashSink_;
        for (uint256 i = 0; i < tiers.length; i++) {
            isTier[tiers[i]] = true;
        }
        usdc_.approve(address(market_), type(uint256).max); // pays the LMSR for the net imbalance
        usdc_.approve(address(router_), type(uint256).max); // router fees (0 in the reference setting)
        usdc_.approve(address(shares_), type(uint256).max); // splits complete sets
    }

    function currentBatch() public view returns (uint256) {
        return (block.number - startBlock) / batchInterval;
    }

    function windowEnd(uint256 batchId) public view returns (uint256) {
        return startBlock + (batchId + 1) * batchInterval; // first block after the commit window
    }

    function batchSize(uint256 batchId) external view returns (uint256) {
        return batches[batchId].length;
    }

    function sealedOrder(uint256 batchId, uint256 index) external view returns (Sealed memory) {
        return batches[batchId][index];
    }

    // ------------------------------------------------------------------ commit

    function commit(uint256 commitment, uint256 escrow, uint256 nullifier, bytes calldata proof)
        external
        returns (uint256 batchId, uint256 index)
    {
        if (!isTier[escrow]) revert NotATier();
        batchId = currentBatch();
        if (address(verifier) != address(0)) {
            bytes32[] memory inputs = new bytes32[](5);
            inputs[0] = bytes32(commitment);
            inputs[1] = bytes32(escrow);
            inputs[2] = bytes32(batchId);
            inputs[3] = bytes32(nullifier);
            inputs[4] = bytes32(registry.root());
            if (!verifier.verify(proof, inputs)) revert InvalidProof();
        } else {
            nullifier = uint256(keccak256(abi.encode(msg.sender, batchId))); // public: one per address per batch
        }
        if (nullifierUsed[nullifier]) revert NullifierUsed();
        nullifierUsed[nullifier] = true;
        usdc.safeTransferFrom(msg.sender, address(this), escrow);
        index = batches[batchId].length;
        batches[batchId].push(Sealed(msg.sender, commitment, escrow, false, 0, 0, 0));
        emit Committed(batchId, index, msg.sender, escrow);
    }

    // ------------------------------------------------------------------ reveal

    function reveal(uint256 batchId, uint256 index, uint8 side, uint256 limit, uint256 size, uint256 salt, uint256 secret)
        external
    {
        if (block.number < windowEnd(batchId)) revert WindowOpen();
        if (cleared[batchId]) revert WindowClosed();
        Sealed storage s = batches[batchId][index];
        if (s.revealed) revert AlreadyRevealed();
        if (commitmentOf(side, limit, size, salt, secret) != s.commitment) revert BadOpening();
        s.revealed = true;
        s.side = side;
        s.limit = limit;
        s.size = size;
        emit Revealed(batchId, index, side, limit, size, _solvent(s));
    }

    /// @notice Poseidon2(side, limit, size, salt, secret): the circuit's order_commitment.
    function commitmentOf(uint8 side, uint256 limit, uint256 size, uint256 salt, uint256 secret)
        public
        pure
        returns (uint256)
    {
        Field.Type[] memory inputs = new Field.Type[](5);
        inputs[0] = Field.Type.wrap(side);
        inputs[1] = Field.Type.wrap(limit);
        inputs[2] = Field.Type.wrap(size);
        inputs[3] = Field.Type.wrap(salt);
        inputs[4] = Field.Type.wrap(secret);
        return Field.Type.unwrap(LibPoseidon2.hash(inputs, 5, false));
    }

    function _solvent(Sealed storage s) private view returns (bool) {
        return s.side <= NO && s.limit > 0 && s.limit < 1_000_000 && s.size > 0 && s.limit * s.size <= s.escrow * 1_000_000;
    }

    // ------------------------------------------------------------------- clear

    function clear(uint256 batchId) external {
        if (block.number < windowEnd(batchId)) revert WindowOpen();
        if (cleared[batchId]) revert AlreadyCleared();
        cleared[batchId] = true;
        Sealed[] storage book = batches[batchId];

        Fill[] memory fills = _validOrders(batchId, book);
        int256 net = _computeFills(fills);
        (uint256 priceYes, uint256 sets) = _trade(net, fills);
        _settle(batchId, book, fills, priceYes);
        emit Cleared(batchId, priceYes, net, sets);
    }

    /// @dev Revealed, solvent orders; everything else forfeits its escrow now.
    function _validOrders(uint256 batchId, Sealed[] storage book) private returns (Fill[] memory fills) {
        uint256 n;
        for (uint256 i = 0; i < book.length; i++) {
            if (book[i].revealed && _solvent(book[i])) n++;
        }
        fills = new Fill[](n);
        uint256 k;
        for (uint256 i = 0; i < book.length; i++) {
            Sealed storage s = book[i];
            if (s.revealed && _solvent(s)) {
                uint256 limit18 = s.limit * 1e12;
                fills[k++] = Fill(i, s.side == YES ? limit18 : ONE - limit18, s.side == YES, s.size, 0);
            } else {
                usdc.safeTransfer(slashSink, s.escrow);
                emit Filled(batchId, i, s.owner, s.side, 0, 0);
            }
        }
    }

    // ---- the price ladder (mirror of sim/tfs/market/batch.py) ----

    function _avgPrice(int256 d) private view returns (uint256) {
        SD59x18 qy = market.qYes();
        SD59x18 qn = market.qNo();
        if (d == 0) return market.priceYes();
        SD59x18 base = market.cost(qy, qn);
        if (d > 0) {
            SD59x18 dw = sd(d * UNIT_TO_WAD);
            return uint256(((market.cost(qy + dw, qn) - base) / dw).unwrap());
        }
        SD59x18 dn = sd(-d * UNIT_TO_WAD);
        return ONE - uint256(((market.cost(qy, qn + dn) - base) / dn).unwrap());
    }

    /// @dev Net YES demand of orders allowing price p; strict excludes orders whose bound equals p.
    function _demand(Fill[] memory fills, uint256 p, bool strict) private pure returns (int256 d) {
        for (uint256 i = 0; i < fills.length; i++) {
            Fill memory f = fills[i];
            bool active = f.yes ? (strict ? f.bound > p : f.bound >= p) : (strict ? f.bound < p : f.bound <= p);
            if (active) d += f.yes ? int256(f.size) : -int256(f.size);
        }
    }

    function _sortedBounds(Fill[] memory fills) private pure returns (uint256[] memory bounds, uint256 n) {
        bounds = new uint256[](fills.length + 2);
        bounds[0] = 0;
        n = 1;
        for (uint256 i = 0; i < fills.length; i++) {
            bounds[n++] = fills[i].bound;
        }
        bounds[n++] = ONE;
        for (uint256 i = 1; i < n; i++) { // insertion sort (batches are small)
            uint256 x = bounds[i];
            uint256 j = i;
            while (j > 0 && bounds[j - 1] > x) {
                bounds[j] = bounds[j - 1];
                j--;
            }
            bounds[j] = x;
        }
    }

    /// @dev Sets each fill; returns the net YES imbalance (6-decimal units).
    function _computeFills(Fill[] memory fills) private view returns (int256 net) {
        if (fills.length == 0) return 0;
        (uint256[] memory b, uint256 n) = _sortedBounds(fills);
        // 1. an interval whose constant demand prices inside it: active orders fill fully
        for (uint256 i = 0; i + 1 < n; i++) {
            if (b[i] == b[i + 1]) continue;
            uint256 mid = (b[i] + b[i + 1]) / 2;
            int256 d = _demand(fills, mid, true);
            uint256 p = _avgPrice(d);
            if (b[i] < p && p < b[i + 1]) {
                for (uint256 k = 0; k < fills.length; k++) {
                    Fill memory f = fills[k];
                    bool active = f.yes ? f.bound > mid : f.bound < mid;
                    f.filled = active ? f.size : 0;
                    if (f.filled > 0) net += f.yes ? int256(f.filled) : -int256(f.filled);
                }
                return net;
            }
        }
        // 2. the crossing sits on a bound: strict orders fill, the margin is rationed
        for (uint256 i = 1; i + 1 < n; i++) {
            if (b[i] == b[i - 1]) continue;
            net = _fillAtBound(fills, b[i]);
            if (net != type(int256).min) return net;
        }
        return 0; // unreachable: a crossing always exists
    }

    function _fillAtBound(Fill[] memory fills, uint256 bound) private view returns (int256) {
        int256 dStrict = _demand(fills, bound, true);
        int256 yesM;
        int256 noM;
        for (uint256 k = 0; k < fills.length; k++) {
            if (fills[k].bound == bound) {
                if (fills[k].yes) yesM += int256(fills[k].size);
                else noM += int256(fills[k].size);
            }
        }
        int256 lo = dStrict - noM;
        int256 hi = dStrict + yesM;
        if (!(_avgPrice(lo) <= bound && bound <= _avgPrice(hi))) return type(int256).min;
        // integer bisection for the imbalance whose average price is the bound
        for (uint256 step = 0; step < BISECTION_STEPS && hi - lo > 1; step++) {
            int256 mid = (lo + hi) / 2;
            if (_avgPrice(mid) < bound) lo = mid;
            else hi = mid;
        }
        int256 dStar = lo;
        int256 extra = dStar - dStrict;
        int256 yesFill = yesM < extra + noM ? yesM : extra + noM; // most matched pairs, then the excess side
        int256 noFill = yesFill - extra;
        int256 net;
        for (uint256 k = 0; k < fills.length; k++) {
            Fill memory f = fills[k];
            if (f.bound == bound) {
                f.filled = f.yes
                    ? (yesM > 0 ? f.size * uint256(yesFill) / uint256(yesM) : 0)
                    : (noM > 0 ? f.size * uint256(noFill) / uint256(noM) : 0);
            } else {
                f.filled = (f.yes ? f.bound > bound : f.bound < bound) ? f.size : 0;
            }
            if (f.filled > 0) net += f.yes ? int256(f.filled) : -int256(f.filled);
        }
        return net;
    }

    // ---- settlement ----

    /// @dev Buy the net imbalance from the LMSR, split complete sets for matched pairs; return the uniform YES price.
    function _trade(int256 net, Fill[] memory fills) private returns (uint256 priceYes, uint256 sets) {
        uint256 yesFilled;
        uint256 noFilled;
        for (uint256 k = 0; k < fills.length; k++) {
            if (fills[k].yes) yesFilled += fills[k].filled;
            else noFilled += fills[k].filled;
        }
        sets = yesFilled < noFilled ? yesFilled : noFilled;
        if (net == 0) {
            priceYes = market.priceYes();
        } else {
            uint8 side = net > 0 ? YES : NO;
            uint256 amount = uint256(net > 0 ? net : -net);
            uint256 before = usdc.balanceOf(address(this));
            router.execute(TradeRouter.Order(market, side, int256(amount), ONE, 0, true));
            uint256 paid = before - usdc.balanceOf(address(this));
            // the LMSR's average price for the imbalance, rounded UP for the side that pays the LMSR:
            // then p*Y + (1-p)*N = sets + p*|net| >= sets + paid, so payments always cover the purchase
            uint256 sidePrice = (paid * ONE + amount - 1) / amount;
            priceYes = net > 0 ? sidePrice : ONE - sidePrice;
        }
        if (sets > 0) shares.split(marketId, sets);
    }

    function _settle(uint256 batchId, Sealed[] storage book, Fill[] memory fills, uint256 priceYes) private {
        for (uint256 k = 0; k < fills.length; k++) {
            Fill memory f = fills[k];
            Sealed storage s = book[f.index];
            uint256 unit = f.yes ? priceYes : ONE - priceYes;
            uint256 paid = (unit * f.filled + ONE - 1) / ONE; // rounded up, in the market's favour
            if (paid > s.escrow) paid = s.escrow; // at the exact solvency boundary rounding can add one unit
            if (f.filled > 0) {
                shares.safeTransferFrom(address(this), s.owner, shares.tokenId(marketId, f.yes ? YES : NO), f.filled, "");
            }
            usdc.safeTransfer(s.owner, s.escrow - paid);
            emit Filled(batchId, f.index, s.owner, s.side, f.filled, paid);
        }
    }
}
