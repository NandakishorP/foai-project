// SPDX-License-Identifier: MIT
pragma solidity 0.8.27;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {ERC1155Holder} from "@openzeppelin/contracts/token/ERC1155/utils/ERC1155Holder.sol";
import {SD59x18, sd} from "@prb/math/src/SD59x18.sol";
import {OutcomeShares} from "./OutcomeShares.sol";

/// @title LMSRMarket
/// @notice Hanson's logarithmic market scoring rule market maker for one binary market (SPEC §4).
///
///   cost  C(q) = b · ln(e^{q_yes/b} + e^{q_no/b})
///   price p_yes = 1 / (1 + e^{(q_no - q_yes)/b})
///
/// q_yes and q_no are the shares traders hold. A trade costs C(q after) − C(q before).
/// C is evaluated with the log-sum-exp trick (subtract max(q)/b before exponentiating),
/// so PRBMath's exp only ever sees arguments ≤ 0 and cannot overflow.
///
/// Inventory, as in Gnosis' market makers: to sell x YES the market maker splits USDC into
/// complete sets through OutcomeShares, hands out the YES and keeps the NO. After every
/// trade it merges surplus YES+NO pairs back into USDC. Collateral stays fully backed
/// (OutcomeShares' invariant) and the market maker's worst-case loss is b·ln 2, funded
/// at deployment.
///
/// Units: share and USDC amounts are 6-decimal integers (1 share pays 1 USDC = 1e6).
/// The LMSR maths runs in 18-decimal SD59x18. Conversions round in the market maker's
/// favour: costs up, proceeds down. This is the Python FastEngine's LMSR (sim/tfs/market/lmsr.py)
/// in fixed point; the differential test bounds the difference.
///
/// Only the TradeRouter may trade, on behalf of the trader it names. The trader approves
/// this contract for USDC and shares; the router passes msg.sender, so nobody can trade
/// with someone else's approvals.
contract LMSRMarket is ERC1155Holder {
    using SafeERC20 for IERC20;

    uint8 public constant YES = 0;
    uint8 public constant NO = 1;
    int256 private constant SCALE = 1e12; // 6-decimal token units -> 18-decimal fixed point

    IERC20 public immutable usdc;
    OutcomeShares public immutable shares;
    uint256 public immutable marketId;
    SD59x18 public immutable b; // liquidity, in shares (18 decimals)
    address public immutable router;

    SD59x18 public qYes; // shares held by traders (18 decimals)
    SD59x18 public qNo;

    event Traded(address indexed trader, uint8 side, int256 amount, int256 cash, uint256 priceYesAfter);

    error OnlyRouter();
    error LimitExceeded(uint256 cash, uint256 limit);
    error BadSide();

    constructor(IERC20 usdc_, OutcomeShares shares_, uint256 marketId_, int256 bWad, address router_) {
        usdc = usdc_;
        shares = shares_;
        marketId = marketId_;
        b = sd(bWad);
        router = router_;
        usdc_.approve(address(shares_), type(uint256).max); // to split USDC into complete sets
    }

    modifier onlyRouter() {
        if (msg.sender != router) revert OnlyRouter();
        _;
    }

    // ------------------------------------------------------------------ maths

    function cost(SD59x18 qy, SD59x18 qn) public view returns (SD59x18) {
        SD59x18 m = qy > qn ? qy : qn;
        SD59x18 sumExp = ((qy - m) / b).exp() + ((qn - m) / b).exp(); // both arguments ≤ 0
        return m + b * sumExp.ln();
    }

    /// @notice YES price with 18 decimals; the NO price is 1e18 minus it.
    function priceYes() public view returns (uint256) {
        if (qNo >= qYes) {
            SD59x18 e = ((qYes - qNo) / b).exp(); // ≤ 1
            return uint256((e / (sd(1e18) + e)).unwrap());
        }
        SD59x18 e2 = ((qNo - qYes) / b).exp();
        return uint256((sd(1e18) / (sd(1e18) + e2)).unwrap());
    }

    /// @notice Cash a trade of `amount` shares (negative = sell) of `side` would cost (negative = receive), 18 decimals.
    function quote18(uint8 side, int256 amount) public view returns (SD59x18) {
        SD59x18 delta = sd(amount * SCALE);
        if (side == YES) return cost(qYes + delta, qNo) - cost(qYes, qNo);
        if (side == NO) return cost(qYes, qNo + delta) - cost(qYes, qNo);
        revert BadSide();
    }

    // ----------------------------------------------------------------- trading

    /// @notice Sell `amount` shares of `side` to `trader` for at most `maxCost` USDC.
    function buy(address trader, uint8 side, uint256 amount, uint256 maxCost) external onlyRouter returns (uint256 paid) {
        int256 c = quote18(side, int256(amount)).unwrap();
        paid = uint256((c + SCALE - 1) / SCALE); // round the cost up (c > 0 for a buy)
        if (paid > maxCost) revert LimitExceeded(paid, maxCost);
        usdc.safeTransferFrom(trader, address(this), paid);
        _move(side, int256(amount));
        _deliver(trader, side, amount);
        _mergeSurplus();
        emit Traded(trader, side, int256(amount), int256(paid), priceYes());
    }

    /// @notice Buy back `amount` shares of `side` from `trader` for at least `minProceeds` USDC.
    function sell(address trader, uint8 side, uint256 amount, uint256 minProceeds)
        external
        onlyRouter
        returns (uint256 received)
    {
        int256 c = -quote18(side, -int256(amount)).unwrap(); // proceeds, 18 decimals
        received = uint256(c / SCALE); // round proceeds down
        if (received < minProceeds) revert LimitExceeded(received, minProceeds);
        shares.safeTransferFrom(trader, address(this), shares.tokenId(marketId, side), amount, "");
        _move(side, -int256(amount));
        _mergeSurplus(); // first turn returned pairs back into USDC: the proceeds may need it
        usdc.safeTransfer(trader, received);
        emit Traded(trader, side, -int256(amount), -int256(received), priceYes());
    }

    function _move(uint8 side, int256 amount) private {
        SD59x18 delta = sd(amount * SCALE);
        if (side == YES) qYes = qYes + delta;
        else qNo = qNo + delta;
    }

    /// @dev Hand `amount` shares to the trader, splitting fresh complete sets if inventory is short.
    function _deliver(address trader, uint8 side, uint256 amount) private {
        uint256 id = shares.tokenId(marketId, side);
        uint256 held = shares.balanceOf(address(this), id);
        if (held < amount) shares.split(marketId, amount - held);
        shares.safeTransferFrom(address(this), trader, id, amount, "");
    }

    /// @dev Turn surplus YES+NO pairs back into USDC, so inventory never holds a complete set.
    function _mergeSurplus() private {
        uint256 yesHeld = shares.balanceOf(address(this), shares.tokenId(marketId, YES));
        uint256 noHeld = shares.balanceOf(address(this), shares.tokenId(marketId, NO));
        uint256 pairs = yesHeld < noHeld ? yesHeld : noHeld;
        if (pairs > 0) shares.merge(marketId, pairs);
    }
}
