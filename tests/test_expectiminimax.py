"""Expectiminimax: a hand-solved tree, and pruned == plain on random games with transpositions."""

import itertools
import random
import zlib
from dataclasses import dataclass

import pytest

from tfs.search.expectiminimax import PLAIN, Node, Options, Searcher, Stats, expectiminimax

# --------------------------------------------------------------------------- #
# A tree small enough to solve by hand
# --------------------------------------------------------------------------- #
# MAX chooses L or R (no reward). Each leads to a CHANCE node (heads 0.5 / tails 0.5),
# then a MIN node whose two actions pay MAX the listed rewards and end the game.
#   L: heads -> MIN{3, 5} = 3   tails -> MIN{1, 4} = 1   expected 2.0
#   R: heads -> MIN{6, 2} = 2   tails -> MIN{4, 4} = 4   expected 3.0   => MAX picks R, value 3
TOY = {
    "root": ("max", {"L": (0, "cL"), "R": (0, "cR")}),
    "cL": ("chance", [(0.5, "mLh"), (0.5, "mLt")]),
    "cR": ("chance", [(0.5, "mRh"), (0.5, "mRt")]),
    "mLh": ("min", {"a": (3, "end"), "b": (5, "end")}),
    "mLt": ("min", {"a": (1, "end"), "b": (4, "end")}),
    "mRh": ("min", {"a": (6, "end"), "b": (2, "end")}),
    "mRt": ("min", {"a": (4, "end"), "b": (4, "end")}),
    "end": ("terminal", None),
}


class ToyGame:
    def node(self, s):
        return Node(TOY[s][0])

    def actions(self, s, ordered):
        return list(TOY[s][1])

    def result(self, s, a):
        return TOY[s][1][a]

    def outcomes(self, s):
        return TOY[s][1]

    def heuristic(self, s):
        return 0.0

    def bounds(self, s):
        return (0.0, 6.0)

    def key(self, s):
        return s


def test_toy_tree_solved_by_hand() -> None:
    assert expectiminimax(ToyGame(), "root", depth=1) == pytest.approx(3.0)
    action, value = Searcher(ToyGame()).best_action("root", depth=1)
    assert (action, value) == ("R", pytest.approx(3.0))


# --------------------------------------------------------------------------- #
# Random games shaped like the order-splitting game
# --------------------------------------------------------------------------- #
# Each block: MAX (no reward) -> MIN (reward in [0, 1]) -> CHANCE -> next block.
# Positions wrap modulo M, so different paths reach the same state (transpositions).
# Everything about a node is a deterministic function of its state, so equal keys mean equal subtrees.


@dataclass(frozen=True)
class S:
    blocks_left: int
    phase: str  # "max", "min" or "chance"
    pos: int


class RandomGame:
    M = 7

    def __init__(self, seed: int, blocks: int) -> None:
        self.seed, self.blocks = seed, blocks

    def _rng(self, *parts: object) -> random.Random:
        return random.Random(zlib.crc32(repr((self.seed, *parts)).encode()))  # reproducible across processes

    def node(self, s: S) -> Node:
        return Node.TERMINAL if s.blocks_left == 0 else Node(s.phase)

    def actions(self, s: S, ordered: bool) -> list[int]:
        n = 2 + self._rng("n", s).randrange(2)
        acts = list(range(n))
        return acts[::-1] if ordered else acts  # any order is legal; values must not change

    def result(self, s: S, a: int) -> tuple[float, S]:
        if s.phase == "max":
            return 0.0, S(s.blocks_left, "min", (s.pos * 3 + a) % self.M)
        return self._rng("r", s, a).random(), S(s.blocks_left, "chance", (s.pos * 5 + a) % self.M)

    def outcomes(self, s: S) -> list[tuple[float, S]]:
        rng = self._rng("c", s)
        weights = [rng.random() + 0.1 for _ in range(2 + rng.randrange(2))]
        total = sum(weights)
        return [(w / total, S(s.blocks_left - 1, "max", (s.pos + k) % self.M)) for k, w in enumerate(weights)]

    def heuristic(self, s: S) -> float:
        return s.blocks_left * self._rng("h", s).random()  # within [0, blocks_left], as bounds() promises

    def bounds(self, s: S) -> tuple[float, float]:
        return (0.0, float(s.blocks_left))  # at most one reward in [0, 1] per remaining block

    def key(self, s: S) -> S:
        return s


ALL_OPTIONS = [Options(*flags) for flags in itertools.product([False, True], repeat=4)]
KEY_OPTIONS = [Options(alphabeta=True, star1=False, ordering=False, transposition=False),
               Options(alphabeta=True, star1=True, ordering=False, transposition=False), Options()]


def _check(seed: int, blocks: int, options_list: list[Options]) -> None:
    depth = 1 + (seed // 3) % blocks
    game = RandomGame(seed, blocks)
    root = S(blocks, "max", seed % RandomGame.M)
    reference = Stats()
    expected = expectiminimax(game, root, depth, reference)
    for options in options_list:
        searcher = Searcher(game, options)
        assert searcher.value(root, depth) == pytest.approx(expected, abs=1e-9), options
        _, best = Searcher(game, options).best_action(root, depth)
        assert best == pytest.approx(expected, abs=1e-9), options
        if options != PLAIN:
            assert searcher.stats.nodes <= reference.nodes, options  # pruning never costs nodes


@pytest.mark.parametrize("seed", range(500))
def test_every_speedup_returns_the_plain_value(seed: int) -> None:
    """All 16 combinations of the four speed-ups, on games of 1-2 blocks."""
    _check(seed, 1 + seed % 2, ALL_OPTIONS)


@pytest.mark.parametrize("seed", range(120))
def test_pruned_value_on_deeper_games(seed: int) -> None:
    """Three-block games (about 20,000 leaves), with the speed-ups added one at a time."""
    _check(seed, 3, KEY_OPTIONS)


def test_pruning_saves_nodes_on_deeper_games() -> None:
    plain, pruned = 0, 0
    for seed in range(20):
        game, root = RandomGame(seed, 3), S(3, "max", seed % RandomGame.M)
        stats = Stats()
        expectiminimax(game, root, 3, stats)
        searcher = Searcher(game, Options())
        searcher.value(root, 3)
        plain, pruned = plain + stats.nodes, pruned + searcher.stats.nodes
    assert pruned < 0.5 * plain


# --------------------------------------------------------------------------- #
# The worked examples of docs/report/walkthroughs/search.md
# --------------------------------------------------------------------------- #
# Example 1 (alpha-beta at a MIN node): MAX picks A or B, then MIN picks a leaf.
#   A -> MIN{3, 5} = 3.  B -> MIN{2, 9}: after seeing 2 (< the 3 MAX already has), B can
#   never be chosen, so the 9 is never looked at.
# Example 2 (Star1 at a CHANCE node): MAX picks A (worth 3, as above) or C. C is a coin
#   flip (0.5 / 0.5) between two leaves, each worth between 0 and 4. The first leaf is worth 1.
#   Even if the second were the best possible 4, C would be worth 0.5*1 + 0.5*4 = 2.5 < 3,
#   so the second leaf is never looked at.
WALK = {
    "root": ("max", {"A": (0, "mA"), "B": (0, "mB")}),
    "mA": ("min", {"a1": (3, "end"), "a2": (5, "end")}),
    "mB": ("min", {"b1": (2, "end"), "b2": (9, "end")}),
    "root2": ("max", {"A": (0, "mA"), "C": (0, "coin")}),
    "coin": ("chance", [(0.5, "m1"), (0.5, "m4")]),
    "m1": ("min", {"x": (1, "end")}),
    "m4": ("min", {"x": (4, "end")}),
    "end": ("terminal", None),
}


class WalkGame(ToyGame):
    def node(self, s):
        return Node(WALK[s][0])

    def actions(self, s, ordered):
        return list(WALK[s][1])

    def result(self, s, a):
        return WALK[s][1][a]

    def outcomes(self, s):
        return WALK[s][1]

    def bounds(self, s):
        return (0.0, 4.0) if s in ("coin", "m1", "m4") else (0.0, 9.0)


def test_walkthrough_example_1_alpha_beta_skips_a_leaf() -> None:
    plain, pruned = Stats(), Searcher(WalkGame(), Options(star1=False, ordering=False, transposition=False))
    assert expectiminimax(WalkGame(), "root", 1, plain) == 3
    assert pruned.best_action("root", 1) == ("A", 3)
    # plain: root, mA, end, end, mB, end, end = 7 nodes; pruned skips B's second leaf
    assert (plain.nodes, pruned.stats.nodes) == (7, 6)


def test_walkthrough_example_2_star1_cuts_a_chance_node() -> None:
    no_star1 = Searcher(WalkGame(), Options(star1=False, ordering=False, transposition=False))
    star1 = Searcher(WalkGame(), Options(ordering=False, transposition=False))
    assert no_star1.best_action("root2", 1) == star1.best_action("root2", 1) == ("A", 3)
    # without Star1 both coin outcomes are searched (m1, end, m4, end); with Star1, m4 and its leaf are skipped
    assert no_star1.stats.nodes - star1.stats.nodes == 2
