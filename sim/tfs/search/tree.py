"""The full game tree, with what a pruned search did to each node (for the dashboard's tree view).

`explain` expands the whole tree exactly as plain expectiminimax would, then runs the pruned
search with recording on, and labels every node:
- "visited": the pruned search looked at it;
- "tt": the pruned search reached it, but the transposition table answered it;
- "pruned": the pruned search never looked at it. Alpha-beta or Star1 cut it off, or an
  ancestor was answered by the table.

A node is identified by its path from the root: the actions (MAX/MIN) and chance-outcome
indices that lead to it. The pruned search uses the same paths, so the two match one to one.
"""

from __future__ import annotations

from dataclasses import dataclass

from tfs.search.expectiminimax import Game, Node, Options, Searcher, Stats, State, expectiminimax


@dataclass(frozen=True)
class TreeNode:
    path: tuple
    kind: Node  # MAX, MIN, CHANCE, or TERMINAL; a MAX node at depth 0 is a heuristic leaf
    leaf: bool  # the search stops here (terminal, or the depth cut-off)
    edge: str  # label of the edge from the parent: the action, or the outcome's probability
    reward: float  # reward on that edge
    value: float  # the node's plain expectiminimax value
    status: str  # "visited", "tt" or "pruned"


@dataclass(frozen=True)
class Explained:
    nodes: list[TreeNode]
    best_action: object
    value: float
    plain: Stats
    pruned: Stats


def _expand(game: Game, state: State, depth: int, path: tuple, edge: str, reward: float,
            out: list[tuple]) -> float:
    """Depth-first expansion in the plain search's order. Appends (path, kind, leaf, edge, reward, value)."""
    kind = game.node(state)
    index = len(out)
    out.append(None)  # placeholder, so parents come before children
    if kind is Node.TERMINAL or (kind is Node.MAX and depth == 0):
        value = 0.0 if kind is Node.TERMINAL else game.heuristic(state)
        out[index] = (path, kind, True, edge, reward, value)
        return value
    if kind is Node.CHANCE:
        value = 0.0
        for i, (p, child) in enumerate(game.outcomes(state)):
            value += p * _expand(game, child, depth, path + (i,), f"p={p:.2f}", 0.0, out)
    else:
        child_depth = depth - 1 if kind is Node.MAX else depth
        values = []
        for action in game.actions(state, ordered=False):
            r, child = game.result(state, action)
            values.append(r + _expand(game, child, child_depth, path + (action,), _label(action), r, out))
        value = max(values) if kind is Node.MAX else min(values)
    out[index] = (path, kind, False, edge, reward, value)
    return value


def _label(action: object) -> str:
    return f"{action:.1f}" if isinstance(action, float) else str(action)


def explain(game: Game, root: State, depth: int, options: Options = Options()) -> Explained:
    """The plain tree, labelled by what the pruned search with `options` did to each node."""
    raw: list[tuple] = []
    _expand(game, root, depth, (), "", 0.0, raw)
    plain = Stats()
    plain_value = expectiminimax(game, root, depth, plain)
    searcher = Searcher(game, options, record={})
    best_action, value = searcher.best_action(root, depth)
    assert abs(value - plain_value) < 1e-9, "pruning must never change the value"
    record = searcher.record or {}
    nodes = [TreeNode(path, kind, leaf, edge, reward, val, record.get(path, "pruned"))
             for path, kind, leaf, edge, reward, val in raw]
    return Explained(nodes, best_action, value, plain, searcher.stats)
