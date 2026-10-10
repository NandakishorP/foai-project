// SPDX-License-Identifier: MIT
pragma solidity 0.8.27;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {ERC1155} from "@openzeppelin/contracts/token/ERC1155/ERC1155.sol";
import {ERC1155Supply} from "@openzeppelin/contracts/token/ERC1155/extensions/ERC1155Supply.sol";

/// @title OutcomeShares
/// @notice YES/NO shares of binary markets, fully backed by collateral (SPEC §4).
/// A simplified, binary version of Gnosis Conditional Tokens (what Polymarket uses):
///   - split:  1 USDC  -> 1 YES + 1 NO   (a "complete set")
///   - merge:  1 YES + 1 NO -> 1 USDC
///   - redeem: after resolution, 1 winning share -> 1 USDC; losing shares are worth 0.
/// Invariant (tested): the USDC held for a market equals its outstanding complete sets
/// before resolution, and the outstanding winning shares after.
/// Token id = marketId * 2 + side, with side YES = 0 and NO = 1. Amounts use USDC's 6 decimals.
contract OutcomeShares is ERC1155Supply {
    using SafeERC20 for IERC20;

    uint8 public constant YES = 0;
    uint8 public constant NO = 1;

    struct Market {
        address oracle; // the only address allowed to report the outcome
        bool resolved;
        uint8 winner; // YES or NO, valid once resolved
    }

    IERC20 public immutable collateral;
    Market[] public markets;
    mapping(uint256 => uint256) public collateralOf; // USDC held per market

    event MarketCreated(uint256 indexed marketId, address oracle);
    event Resolved(uint256 indexed marketId, uint8 winner);

    error NotOracle();
    error AlreadyResolved();
    error NotResolved();
    error BadSide();

    constructor(IERC20 collateral_) ERC1155("") {
        collateral = collateral_;
    }

    function tokenId(uint256 marketId, uint8 side) public pure returns (uint256) {
        if (side > NO) revert BadSide();
        return marketId * 2 + side;
    }

    function marketCount() external view returns (uint256) {
        return markets.length;
    }

    /// @notice Register a market whose outcome `oracle` will report.
    function createMarket(address oracle) external returns (uint256 marketId) {
        marketId = markets.length;
        markets.push(Market({oracle: oracle, resolved: false, winner: 0}));
        emit MarketCreated(marketId, oracle);
    }

    function split(uint256 marketId, uint256 amount) external {
        if (markets[marketId].resolved) revert AlreadyResolved();
        collateral.safeTransferFrom(msg.sender, address(this), amount);
        collateralOf[marketId] += amount;
        _mint(msg.sender, tokenId(marketId, YES), amount, "");
        _mint(msg.sender, tokenId(marketId, NO), amount, "");
    }

    function merge(uint256 marketId, uint256 amount) external {
        if (markets[marketId].resolved) revert AlreadyResolved();
        _burn(msg.sender, tokenId(marketId, YES), amount);
        _burn(msg.sender, tokenId(marketId, NO), amount);
        collateralOf[marketId] -= amount;
        collateral.safeTransfer(msg.sender, amount);
    }

    function reportOutcome(uint256 marketId, uint8 winner) external {
        Market storage m = markets[marketId];
        if (msg.sender != m.oracle) revert NotOracle();
        if (m.resolved) revert AlreadyResolved();
        if (winner > NO) revert BadSide();
        m.resolved = true;
        m.winner = winner;
        emit Resolved(marketId, winner);
    }

    /// @notice Burn all of the caller's shares in a resolved market; pay 1 USDC per winning share.
    function redeem(uint256 marketId) external returns (uint256 paid) {
        Market storage m = markets[marketId];
        if (!m.resolved) revert NotResolved();
        uint256 winId = tokenId(marketId, m.winner);
        uint256 loseId = tokenId(marketId, m.winner == YES ? NO : YES);
        paid = balanceOf(msg.sender, winId);
        uint256 losing = balanceOf(msg.sender, loseId);
        if (paid > 0) _burn(msg.sender, winId, paid);
        if (losing > 0) _burn(msg.sender, loseId, losing);
        collateralOf[marketId] -= paid;
        collateral.safeTransfer(msg.sender, paid);
    }
}
