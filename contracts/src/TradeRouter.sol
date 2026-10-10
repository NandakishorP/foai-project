// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {LMSRMarket} from "./LMSRMarket.sol";

/// @title TradeRouter
/// @notice Every trade goes through here. It reproduces the FastEngine's fee rules on-chain
/// (DECISIONS D-012, D-034) so the two engines can be compared transaction by transaction:
///   - a plain order pays `baseFee + priorityFee` USDC to the builder and then tries the trade;
///     a failing trade does not refund the fee (like gas spent on a reverted transaction);
///   - a revert-protected order (searchers' front-runs) either fills and pays, or reverts
///     entirely and pays nothing;
///   - a bundle's orders fill all-or-nothing, fees included (arbitrage).
/// Limits are average prices with 18 decimals, as in the Python `Trade`: a buy may cost at
/// most limit × amount, and a sell must return at least limit × amount.
contract TradeRouter {
    using SafeERC20 for IERC20;

    struct Order {
        LMSRMarket market;
        uint8 side; // 0 = YES, 1 = NO
        int256 amount; // shares, 6 decimals; positive = buy, negative = sell
        uint256 limitPrice; // average price bound, 18 decimals
        uint256 priorityFee; // tip to the builder, USDC 6 decimals
        bool revertProtected;
    }

    IERC20 public immutable usdc;
    address public immutable builder;
    uint256 public immutable baseFee;

    event OrderResult(address indexed trader, bool ok);
    event BundleResult(address indexed trader, uint256 legs);

    error OnlySelf();
    error ZeroAmount();

    constructor(IERC20 usdc_, address builder_, uint256 baseFee_) {
        usdc = usdc_;
        builder = builder_;
        baseFee = baseFee_;
    }

    function execute(Order calldata o) external returns (bool ok) {
        uint256 fee = baseFee + o.priorityFee;
        if (o.revertProtected) {
            _trade(msg.sender, o); // any failure reverts the whole transaction: nothing is paid
            _payFee(msg.sender, fee);
            ok = true;
        } else {
            _payFee(msg.sender, fee); // paid on inclusion, whether or not the trade fills
            try this.tradeFor(msg.sender, o) {
                ok = true;
            } catch {
                ok = false;
            }
        }
        emit OrderResult(msg.sender, ok);
    }

    function executeBundle(Order[] calldata orders) external {
        for (uint256 i = 0; i < orders.length; i++) {
            _payFee(msg.sender, baseFee + orders[i].priorityFee);
            _trade(msg.sender, orders[i]); // any failure reverts every leg and every fee
        }
        emit BundleResult(msg.sender, orders.length);
    }

    /// @dev External only so `execute` can wrap it in try/catch; callable by this contract alone.
    function tradeFor(address trader, Order calldata o) external {
        if (msg.sender != address(this)) revert OnlySelf();
        _trade(trader, o);
    }

    function _trade(address trader, Order calldata o) private {
        if (o.amount == 0) revert ZeroAmount();
        if (o.amount > 0) {
            uint256 amount = uint256(o.amount);
            uint256 maxCost = (o.limitPrice * amount + 1e18 - 1) / 1e18; // limit × amount, rounded up
            o.market.buy(trader, o.side, amount, maxCost);
        } else {
            uint256 amount = uint256(-o.amount);
            uint256 minProceeds = (o.limitPrice * amount) / 1e18; // limit × amount, rounded down
            o.market.sell(trader, o.side, amount, minProceeds);
        }
    }

    function _payFee(address trader, uint256 fee) private {
        if (fee > 0) usdc.safeTransferFrom(trader, builder, fee);
    }
}
