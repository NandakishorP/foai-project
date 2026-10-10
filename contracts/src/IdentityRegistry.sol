// SPDX-License-Identifier: MIT
pragma solidity 0.8.27;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {LibPoseidon2Yul} from "poseidon2-evm/bn254/yul/LibPoseidon2Yul.sol";

/// @title IdentityRegistry
/// @notice Registered trader identities for sealed orders (DECISIONS D-002).
/// A trader registers leaf = Poseidon2(trader_secret) and locks a stake; the stake is what
/// makes creating many identities costly (sybil resistance). The leaves form a depth-8
/// Poseidon2 Merkle tree. The sealed_order circuit proves membership under `root()` without
/// revealing which leaf, so a commitment is tied to *some* registered identity.
/// Hashes match Noir's (test/Poseidon2Compat.t.sol). The tree hashes children as
/// Poseidon2(left, right), exactly as circuits/order_lib's merkle_root.
contract IdentityRegistry {
    using SafeERC20 for IERC20;

    uint256 public constant DEPTH = 8;
    uint256 public constant CAPACITY = 1 << DEPTH;

    IERC20 public immutable usdc;
    uint256 public immutable stake;
    uint256[] public leaves;
    uint256 public root;
    mapping(uint256 => bool) public registered;

    event Registered(uint256 indexed index, uint256 leaf);

    error AlreadyRegistered();
    error RegistryFull();
    error NoSuchLeaf();

    constructor(IERC20 usdc_, uint256 stake_) {
        usdc = usdc_;
        stake = stake_;
        root = _rootOf(new uint256[](0));
    }

    function register(uint256 leaf) external returns (uint256 index) {
        if (registered[leaf]) revert AlreadyRegistered();
        if (leaves.length >= CAPACITY) revert RegistryFull();
        usdc.safeTransferFrom(msg.sender, address(this), stake);
        index = leaves.length;
        leaves.push(leaf);
        registered[leaf] = true;
        root = _rootOf(leaves);
        emit Registered(index, leaf);
    }

    function size() external view returns (uint256) {
        return leaves.length;
    }

    /// @notice Sibling path and position bits of leaf `index` under the current root (for the prover).
    function path(uint256 index) external view returns (uint256[DEPTH] memory siblings, uint8[DEPTH] memory bits) {
        if (index >= leaves.length) revert NoSuchLeaf();
        uint256[] memory level = _padded(leaves);
        uint256 pos = index;
        for (uint256 d = 0; d < DEPTH; d++) {
            bits[d] = uint8(pos & 1);
            siblings[d] = level[pos ^ 1];
            level = _parents(level);
            pos >>= 1;
        }
    }

    function _rootOf(uint256[] memory xs) private pure returns (uint256) {
        uint256[] memory level = _padded(xs);
        for (uint256 d = 0; d < DEPTH; d++) {
            level = _parents(level);
        }
        return level[0];
    }

    /// @dev All CAPACITY leaves, empty slots as 0 (the circuit's convention for an absent sibling).
    function _padded(uint256[] memory xs) private pure returns (uint256[] memory level) {
        level = new uint256[](CAPACITY);
        for (uint256 i = 0; i < xs.length; i++) {
            level[i] = xs[i];
        }
    }

    function _parents(uint256[] memory level) private pure returns (uint256[] memory up) {
        up = new uint256[](level.length / 2);
        for (uint256 i = 0; i < up.length; i++) {
            up[i] = LibPoseidon2Yul.hash_2(level[2 * i], level[2 * i + 1]);
        }
    }
}
