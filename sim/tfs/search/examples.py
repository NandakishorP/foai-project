"""Small hand-solvable game trees: the worked examples of docs/report/walkthroughs/search.md.

Used by the tests (they check every number in the walkthrough) and by the dashboard's tree
view. A tree is a dict: node name -> (kind, children). MAX/MIN children are
{action: (reward, child)}; CHANCE children are [(probability, child)].

Example 1 (alpha-beta at a MIN node): MAX picks A or B, then MIN picks a leaf.
    A -> MIN{3, 5} = 3.  B -> MIN{2, 9}: after seeing 2 (< the 3 MAX already has), B can never
    be chosen, so the 9 is never looked at.
Example 2 (Star1 at a CHANCE node): MAX picks A (worth 3) or C. C is a coin flip between two
    leaves known to lie in [0, 4]. The first is worth 1. Even if the second were 4, C would be
    worth 0.5·1 + 0.5·4 = 2.5 < 3, so the second leaf is never looked at.
"""

from __future__ import annotations

from tfs.search.expectiminimax import Node

TREES = {
    "root": ("max", {"A": (0, "mA"), "B": (0, "mB")}),
    "mA": ("min", {"a1": (3, "end"), "a2": (5, "end")}),
    "mB": ("min", {"b1": (2, "end"), "b2": (9, "end")}),
    "root2": ("max", {"A": (0, "mA"), "C": (0, "coin")}),
    "coin": ("chance", [(0.5, "m1"), (0.5, "m4")]),
    "m1": ("min", {"x": (1, "end")}),
    "m4": ("min", {"x": (4, "end")}),
    "end": ("terminal", None),
}
EXAMPLE_1, EXAMPLE_2 = "root", "root2"


class TreeGame:
    """A game read from TREES (the Game interface of tfs.search.expectiminimax)."""

    def node(self, s: str) -> Node:
        return Node(TREES[s][0])

    def actions(self, s: str, ordered: bool) -> list[str]:
        return list(TREES[s][1])

    def result(self, s: str, a: str) -> tuple[float, str]:
        return TREES[s][1][a]

    def outcomes(self, s: str) -> list[tuple[float, str]]:
        return TREES[s][1]

    def heuristic(self, s: str) -> float:
        return 0.0

    def bounds(self, s: str) -> tuple[float, float]:
        return (0.0, 4.0) if s in ("coin", "m1", "m4") else (0.0, 9.0)

    def key(self, s: str) -> str:
        return s
