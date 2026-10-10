// SPDX-License-Identifier: MIT
pragma solidity 0.8.27;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {OutcomeShares} from "./OutcomeShares.sol";

/// @title OptimisticOracle
/// @notice Resolves markets by optimistic proposal with a dispute window (SPEC §4):
///   1. anyone proposes an outcome, posting a bond;
///   2. during the dispute window anyone may dispute, posting an equal bond;
///   3. undisputed: after the window the proposal stands and the proposer's bond is returned;
///      disputed: the question escalates to a "vote". Here a `resolver` address stands in for
///      it; the simulation drives it with an honest-majority process (probability
///      p_vote_correct, Phase 3 / E6). The winner receives both bonds minus a burn.
/// This is the on-chain side of the oracle game; the agents' bond-game strategies are Phase 3.
contract OptimisticOracle {
    using SafeERC20 for IERC20;

    enum Status {
        None,
        Proposed,
        Disputed,
        Settled
    }

    struct Request {
        address proposer;
        address disputer;
        uint8 outcome;
        uint64 proposedAt;
        Status status;
    }

    IERC20 public immutable usdc;
    OutcomeShares public immutable shares;
    uint256 public immutable bond; // USDC, 6 decimals
    uint256 public immutable window; // seconds
    uint256 public immutable burnBps; // share of the loser's bond that is burned, in basis points
    address public immutable resolver; // stand-in for the escalation vote
    address public constant BURN = address(0xdead);

    mapping(uint256 => Request) public requests;

    event Proposed(uint256 indexed marketId, address proposer, uint8 outcome);
    event Disputed(uint256 indexed marketId, address disputer);
    event Settled(uint256 indexed marketId, uint8 outcome, address bondWinner);

    error WrongStatus();
    error WindowOpen();
    error WindowClosed();
    error OnlyResolver();

    constructor(IERC20 usdc_, OutcomeShares shares_, uint256 bond_, uint256 window_, uint256 burnBps_, address resolver_) {
        usdc = usdc_;
        shares = shares_;
        bond = bond_;
        window = window_;
        burnBps = burnBps_;
        resolver = resolver_;
    }

    function propose(uint256 marketId, uint8 outcome) external {
        Request storage r = requests[marketId];
        if (r.status != Status.None) revert WrongStatus();
        usdc.safeTransferFrom(msg.sender, address(this), bond);
        r.proposer = msg.sender;
        r.outcome = outcome;
        r.proposedAt = uint64(block.timestamp);
        r.status = Status.Proposed;
        emit Proposed(marketId, msg.sender, outcome);
    }

    function dispute(uint256 marketId) external {
        Request storage r = requests[marketId];
        if (r.status != Status.Proposed) revert WrongStatus();
        if (block.timestamp >= r.proposedAt + window) revert WindowClosed();
        usdc.safeTransferFrom(msg.sender, address(this), bond);
        r.disputer = msg.sender;
        r.status = Status.Disputed;
        emit Disputed(marketId, msg.sender);
    }

    /// @notice Finalise an undisputed proposal after the window.
    function settle(uint256 marketId) external {
        Request storage r = requests[marketId];
        if (r.status != Status.Proposed) revert WrongStatus();
        if (block.timestamp < r.proposedAt + window) revert WindowOpen();
        r.status = Status.Settled;
        usdc.safeTransfer(r.proposer, bond);
        shares.reportOutcome(marketId, r.outcome);
        emit Settled(marketId, r.outcome, r.proposer);
    }

    /// @notice The vote's result for a disputed proposal. The side it agrees with wins both bonds minus the burn.
    function resolveDispute(uint256 marketId, uint8 outcome) external {
        if (msg.sender != resolver) revert OnlyResolver();
        Request storage r = requests[marketId];
        if (r.status != Status.Disputed) revert WrongStatus();
        r.status = Status.Settled;
        address winner = outcome == r.outcome ? r.proposer : r.disputer;
        uint256 burned = (bond * burnBps) / 10_000;
        usdc.safeTransfer(BURN, burned);
        usdc.safeTransfer(winner, 2 * bond - burned);
        shares.reportOutcome(marketId, outcome);
        emit Settled(marketId, outcome, winner);
    }
}
