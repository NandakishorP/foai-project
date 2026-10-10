"""Expectiminimax, plain and with pruning (course concept: adversarial search).

A game tree has three kinds of nodes:
- MAX: the player we search for picks the action with the highest value;
- MIN: the adversary picks the action with the lowest value;
- CHANCE: nature picks an outcome at random; the value is the probability-weighted mean.

Rewards sit on the edges (`Game.result` returns `(reward, child)`), so a node's value is
the best total reward still to come from it. Depth counts MAX turns: at a MAX node with
depth 0 the search stops and uses the game's heuristic estimate instead.

Two functions:
- `expectiminimax` is the plain textbook recursion. It is the reference: short enough to
  check by hand, and every pruned search must return exactly its value.
- `search` adds four optional speed-ups, each switchable so the node-count chart can show
  what each one buys:
  1. **alpha-beta** on MAX/MIN nodes: stop looking at a node's remaining actions once
     it is certain the parent will not choose this node.
  2. **Star1** at CHANCE nodes (Ballard 1983): plain alpha-beta cannot cut a chance
     node, because one unseen outcome could still move the average anywhere. If the game
     gives *bounds* on every value, it can: once even the best (worst) case for the
     unseen outcomes cannot bring the average back inside the window, stop.
  3. **move ordering**: try the actions most likely to be best first, so cut-offs come early.
  4. a **transposition table**: a state reached again by another path at the same
     depth is not searched again. Values found under a narrow window are only bounds,
     and are stored as such.
"""

from __future__ import annotations

import math
from collections.abc import Hashable, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

State = Any
Action = Any


class Node(Enum):
    MAX = "max"
    MIN = "min"
    CHANCE = "chance"
    TERMINAL = "terminal"


class Game(Protocol):
    """What a game must provide to be searched."""

    def node(self, state: State) -> Node: ...

    def actions(self, state: State, ordered: bool) -> Sequence[Action]:
        """Legal actions at a MAX or MIN node; `ordered` asks for the most promising first."""
        ...

    def result(self, state: State, action: Action) -> tuple[float, State]:
        """(reward to MAX on this edge, next state)."""
        ...

    def outcomes(self, state: State) -> Sequence[tuple[float, State]]:
        """(probability, next state) at a CHANCE node; probabilities sum to 1; no reward on these edges."""
        ...

    def heuristic(self, state: State) -> float:
        """Estimated value of a MAX node where the search stops (depth 0)."""
        ...

    def bounds(self, state: State) -> tuple[float, float]:
        """Values every node below `state` is guaranteed to stay within (needed by Star1)."""
        ...

    def key(self, state: State) -> Hashable:
        """Transposition-table key: equal keys must mean equal states."""
        ...


@dataclass
class Stats:
    """Nodes expanded by one search (every node visited counts once)."""

    nodes: int = 0
    tt_hits: int = 0


@dataclass(frozen=True)
class Options:
    alphabeta: bool = True
    star1: bool = True
    ordering: bool = True
    transposition: bool = True


PLAIN = Options(alphabeta=False, star1=False, ordering=False, transposition=False)


# --------------------------------------------------------------------------- #
# The reference: plain expectiminimax
# --------------------------------------------------------------------------- #


def expectiminimax(game: Game, state: State, depth: int, stats: Stats | None = None) -> float:
    """Exact value of `state` searched `depth` MAX turns deep, with no pruning at all."""
    stats = stats if stats is not None else Stats()
    stats.nodes += 1
    kind = game.node(state)
    if kind is Node.TERMINAL:
        return 0.0
    if kind is Node.CHANCE:
        return sum(p * expectiminimax(game, child, depth, stats) for p, child in game.outcomes(state))
    if kind is Node.MAX and depth == 0:
        return game.heuristic(state)
    child_depth = depth - 1 if kind is Node.MAX else depth
    values = []
    for action in game.actions(state, ordered=False):
        reward, child = game.result(state, action)
        values.append(reward + expectiminimax(game, child, child_depth, stats))
    return max(values) if kind is Node.MAX else min(values)


# --------------------------------------------------------------------------- #
# The pruned search
# --------------------------------------------------------------------------- #


class Bound(Enum):
    EXACT = "exact"
    LOWER = "lower"  # the true value is at least the stored one
    UPPER = "upper"  # the true value is at most the stored one


@dataclass
class Searcher:
    """One pruned search configuration; keeps its transposition table between calls on the same game."""

    game: Game
    options: Options = Options()
    stats: Stats = field(default_factory=Stats)
    table: dict[tuple[Hashable, int], tuple[float, Bound]] = field(default_factory=dict)

    def value(self, state: State, depth: int) -> float:
        """Exact value of `state` (searched with the full window)."""
        return self._value(state, depth, -math.inf, math.inf)

    def best_action(self, state: State, depth: int) -> tuple[Action, float]:
        """The MAX action with the highest value at a MAX root, and that value."""
        assert self.game.node(state) is Node.MAX and depth >= 1
        self.stats.nodes += 1
        best_action, best = None, -math.inf
        for action in self.game.actions(state, ordered=self.options.ordering):
            reward, child = self.game.result(state, action)
            alpha = best - reward if self.options.alphabeta else -math.inf
            v = reward + self._value(child, depth - 1, alpha, math.inf)
            if v > best:  # ties keep the earlier action, so the result does not depend on chance
                best_action, best = action, v
        return best_action, best

    def _value(self, state: State, depth: int, alpha: float, beta: float) -> float:
        """Value of `state`, exact if it lies inside (alpha, beta); otherwise a bound on the far side."""
        self.stats.nodes += 1
        kind = self.game.node(state)
        if kind is Node.TERMINAL:
            return 0.0
        if kind is Node.MAX and depth == 0:
            return self.game.heuristic(state)

        key = (self.game.key(state), depth) if self.options.transposition else None
        if key is not None and key in self.table:
            stored, bound = self.table[key]
            if bound is Bound.EXACT or (bound is Bound.LOWER and stored >= beta) or (
                    bound is Bound.UPPER and stored <= alpha):
                self.stats.tt_hits += 1
                return stored

        if kind is Node.CHANCE:
            v = self._chance(state, depth, alpha, beta)
        else:
            v = self._decision(state, kind, depth, alpha, beta)

        if key is not None:
            bound = Bound.UPPER if v <= alpha else Bound.LOWER if v >= beta else Bound.EXACT
            self.table[key] = (v, bound)
        return v

    def _decision(self, state: State, kind: Node, depth: int, alpha: float, beta: float) -> float:
        """MAX or MIN node. With alpha-beta, stop as soon as the value leaves the window."""
        child_depth = depth - 1 if kind is Node.MAX else depth
        best = -math.inf if kind is Node.MAX else math.inf
        for action in self.game.actions(state, ordered=self.options.ordering):
            reward, child = self.game.result(state, action)
            if self.options.alphabeta:  # the child's window, shifted by the reward on the edge
                v = reward + self._value(child, child_depth, alpha - reward, beta - reward)
            else:
                v = reward + self._value(child, child_depth, -math.inf, math.inf)
            if kind is Node.MAX:
                best = max(best, v)
                if self.options.alphabeta:
                    alpha = max(alpha, best)
            else:
                best = min(best, v)
                if self.options.alphabeta:
                    beta = min(beta, best)
            if self.options.alphabeta and alpha >= beta:
                break  # the parent will never let play reach here: the remaining actions cannot matter
        return best

    def _chance(self, state: State, depth: int, alpha: float, beta: float) -> float:
        """CHANCE node: the expected value. With Star1, stop once the window is out of reach."""
        outcomes = self.game.outcomes(state)
        if not (self.options.star1 and self.options.alphabeta):
            return sum(p * self._value(child, depth, -math.inf, math.inf) for p, child in outcomes)

        # Star1: lo/hi are the bounds of each child's value; `done` is the weighted sum seen so far.
        child_bounds = [self.game.bounds(child) for _, child in outcomes]
        rest_lo = sum(p * lo for (p, _), (lo, _) in zip(outcomes, child_bounds))
        rest_hi = sum(p * hi for (p, _), (_, hi) in zip(outcomes, child_bounds))
        done = 0.0
        for (p, child), (lo, hi) in zip(outcomes, child_bounds):
            rest_lo -= p * lo
            rest_hi -= p * hi
            # The window this child must hit for the average to land inside (alpha, beta),
            # assuming the best case (hi) and worst case (lo) for the children not yet seen.
            child_alpha = max(lo, (alpha - done - rest_hi) / p)
            child_beta = min(hi, (beta - done - rest_lo) / p)
            v = self._value(child, depth, child_alpha, child_beta)
            done += p * v
            if done + rest_hi <= alpha:
                return done + rest_hi  # even the best case for the rest stays below alpha
            if done + rest_lo >= beta:
                return done + rest_lo  # even the worst case for the rest stays above beta
        return done
