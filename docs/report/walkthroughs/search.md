# Walkthrough: the order-splitting search (expectiminimax, alpha-beta, Star1, transposition table)

*For review preparation. Plain language first, then the code with file and line references, then two small trees you can work by hand, then likely questions with answers. Line numbers refer to commit `42743ad` and later.*

---

## 1. The problem in one paragraph
A forecaster has found an edge: it believes YES is worth more than the market price, and its Kelly rule says it should buy R more shares (`KellyTrader.next_trade`, `sim/tfs/agents/kelly_trader.py:84`).
- **Why not buy all R at once?** On a public mempool a predator sees the order before it executes, and can buy first and profit from the price move the forecaster is about to cause.
- **Why not wait?** Other traders close the gap meanwhile, and the edge disappears.

"How much of R to send *this* block" is a game between the forecaster (MAX), the predator (MIN) and randomness (CHANCE). Expectiminimax solves it.

## 2. The game (`sim/tfs/search/order_splitting.py`)
One block of the game is three layers, then the next block.

| Layer | Who | Choices | Code |
|---|---|---|---|
| MAX | the forecaster | slice q ∈ {0, R/8, R/4, R/2, R}, never past its belief | `actions` (line 164), `SLICE_FRACTIONS` (line 56) |
| MIN | the predator | front-run f ∈ {0, x_max/2, x_max}, only if it expects a profit | `_allowed_front_runs` (line 222) |
| CHANCE | the world | noise ±σ (½ each) × news {none, up, down} | `outcomes` (line 178) |

- **Reward.** MAX earns q·(belief − average price paid) when its slice executes after the front-run (`_execute`, line 215). MIN's choice changes that price. The reward sits on the MIN → CHANCE edge (`result`, line 172).
- **MIN is "rational worst case".** It hurts MAX as much as it can, but only with front-runs it expects to profit from:
  - it uses exactly the simulation predator's EV formula (`front_run_ev` in `agents/predator.py`) and its measured beliefs (line 232; D-054);
  - its allowed set is filtered at line 237.
- **CHANCE.**
  - Other traders close a share κ = 0.87 of the gap each block (line 180, measured: D-054).
  - Noise moves the price by ±σ.
  - News moves belief and price together, so it changes the level, not the gap (line 182).
- **The game is on a grid.** Prices and beliefs are rounded to 0.01 log-odds and R to a geometric grid (`snap_logit`, `snap_size`, lines 135–145). Equal grid states are *exactly* equal, so remembering a state's value is exact (section 5).

## 3. The plain recursion (`sim/tfs/search/expectiminimax.py:102`)
`expectiminimax(game, state, depth)` is the textbook definition, about 15 lines:
- **TERMINAL:** 0 (no more reward).
- **CHANCE:** Σ probability × value(child).
- **MAX with depth 0:** the heuristic estimate (`heuristic`, order_splitting line 191: "send the rest now; the predator answers with its worst allowed front-run").
- **MAX:** max over actions of reward + value(child), with depth − 1 below.
- **MIN:** min over actions of reward + value(child).

**Depth counts MAX turns, i.e. blocks.** Depth 3 = three blocks of MAX, MIN and CHANCE. Every faster search must return *exactly* this value. Tests check that on 620 random games (`tests/test_expectiminimax.py`) and on the real game (`tests/test_order_splitting.py`).

## 4. The pruned search (`Searcher`, `expectiminimax.py:133`)
Four switchable speed-ups (`Options`, line 87), so the benchmark can show what each one buys.

### 4.1 Alpha-beta at MAX and MIN nodes (`_decision`, line 185)
- **The window.** alpha = the best value MAX is already guaranteed elsewhere; beta = the best MIN is guaranteed elsewhere. A node's exact value only matters if it falls inside (alpha, beta).
- **The cut-off.** At a MIN node, once one action gives a value ≤ alpha, MAX will never come here. The remaining actions are skipped (`break`, line 204). The same holds symmetrically at MAX nodes.
- **Rewards on edges shift the window.** The child is searched with (alpha − reward, beta − reward) (line 192).

### 4.2 Star1 at CHANCE nodes (`_chance`, line 207)
- **Why plain alpha-beta stops at chance nodes.** A chance node is an average: one unseen outcome could still move it anywhere.
- **What bounds make possible (Ballard 1983).** If every value is known to lie in [lo, hi] (`bounds`, order_splitting line 199), you can stop once even the best case (or worst case) for the unseen outcomes cannot bring the average back inside the window (lines 226–230).
- **Each child gets a narrowed window** (lines 223–224), so the cut-offs cascade.
- **Why the bounds are valid here.**
  - A slice never fills at a loss, so lo = 0.
  - Per share, MAX can earn at most sigmoid(belief) − sigmoid(price) ≤ tanh(gap/4).
  - The gap only shrinks, except by noise and rounding, which the bound allows for (line 208).

### 4.3 Move ordering
- **MAX:** after news, try big slices first; otherwise small first (order_splitting line 168).
- **MIN:** try the biggest front-run first (line 170).
- Good ordering makes cut-offs come earlier. It never changes values.

### 4.4 Transposition table (`_value`, lines 166–182)
- **The same state reached by two paths is searched once.** The key is (phase, belief, price, R, slice) plus depth (line 211). The grid (section 2) makes equal keys mean equal states.
- **A value found under a narrow window may only be a bound.** It is stored with its type, EXACT / LOWER / UPPER (lines 126, 181), and reused only when that type settles the question (lines 170–171).
- **The table lives for one season** (`SplittingPolicy`, order_splitting line 244). Decisions already solved are reused for the season's later blocks, never globally.

### 4.5 Choosing the move (`best_action`, line 145)
- The root tries every MAX action and keeps the best.
- Ties keep the earlier action (line 154), so the result is deterministic.
- The forecaster sends that fraction of its real R, never past its belief (`SplittingPolicy.slice`, line 267; `SearchSlice.size`, `agents/slicing.py:78`).
- **It replans every block** (receding horizon).

## 5. Two trees to work by hand (both are tests: `tests/test_expectiminimax.py`, "walkthrough")

**Example 1: alpha-beta at a MIN node.**
```
            MAX
          /     \
         A       B
        MIN     MIN
       /   \   /   \
      3     5 2     9
```
1. A: MIN picks min(3, 5) = 3. MAX now has alpha = 3.
2. B: the first leaf is 2. MIN can already force ≤ 2 < 3, so MAX will never pick B. The 9 is never examined.
3. Value 3, action A. Nodes: 7 for the plain search, 6 pruned.

**Example 2: Star1 at a CHANCE node** (every leaf is known to be in [0, 4]).
```
            MAX
          /     \
         A       C (coin: ½ / ½)
       MIN       /     \
      3   5     1       ?   (? ∈ [0, 4])
```
1. A is worth 3, as before, so alpha = 3.
2. C: the first outcome is 1. Even if "?" were the maximum, 4, C would be worth ½·1 + ½·4 = 2.5 < 3.
3. So "?" is never examined. Star1 saves 2 nodes here. Plain alpha-beta could not cut, because it does not use the bound 4.

## 6. Measured on the real game (E4-search, `docs/report/phase3b/e4_search/`)
500 game states that the forecasters actually searched in E4 seasons, each searched from scratch. Plain expectiminimax at depth 5 ran on the first 50 states only (about 1.9M nodes each). Every pruned value equals the plain value (largest difference 2.2e-16, rounding).

| depth | plain | alpha-beta | + Star1 | + ordering | + transposition table |
|---|---|---|---|---|---|
| 1 | 42 nodes · 0.12 ms | 41 · 0.10 | 39 · 0.12 | 30 · 0.09 | 30 · 0.10 |
| 2 | 639 · 1.5 ms | 620 · 1.4 | 587 · 1.7 | 383 · 1.2 | 360 · 1.1 |
| 3 | 7,660 · 17 ms | 7,388 · 17 | 7,057 · 20 | 3,911 · 12 | **1,486 · 4.6 ms** |
| 4 | 89,862 · 197 ms | 86,425 · 195 | 82,348 · 236 | 39,045 · 115 | **3,469 · 10.5 ms** |
| 5 | 1,873,458 · 5.6 s | 999,901 · 2.3 s | 947,857 · 2.7 s | 382,880 · 1.1 s | **6,332 · 20 ms** |

How to read it, honestly:
- **Alpha-beta alone saves little here:** 4% at depth 4. At depth 5 the plain figure comes from a 50-state subsample, so the two are not directly comparable.
  - Cut-offs need a MIN node with several real choices. In this game the predator usually has only one *allowed* front-run, because front-running a small slice is rarely profitable, so most MIN nodes have one child.
  - Every chance layer also resets the window for plain alpha-beta.
- **Star1 removes a few more nodes but is *slower*.** Computing every child's bounds at every chance node costs more than the nodes it saves. A real trade-off, worth stating rather than hiding.
- **Move ordering roughly halves the tree.** Trying the most damaging front-run first makes the MIN cut-offs come earlier.
- **The transposition table is the big win:** 26× fewer nodes than plain at depth 4 (same 500 states), and 60× fewer than ordering alone at depth 5 (382,880 → 6,332, same states). Because states live on a grid, many paths (slice, front-run, noise outcome) lead to the same state, which is then searched once. The table is what makes depth 4–5 affordable.
- **Growth with depth:** the full search grows about 2× per extra block, where plain grows about 12–20×.

In a full 30-market season at depth 3 (one table kept for the season), the forecasters solved about 5,700 distinct root states and expanded about 1.5M nodes; 17% of node visits were answered by the table. A season took 7.4 s, against 1.7 s for the capped rule.

## 7. What it achieved, and why it lost (E4; D-055)
- **The algorithm is correct and efficient** (section 6, and the tests in section 3).
- **The strategy lost** to TWAP: R4 = 0.901 [0.890, 0.912]; H4 contradicted.
- **The reason is the model, not the search.** The game has one predator and a fixed competitor push. In the market, nine other researchers with the same signal send the same order at the same limit in the same block. TWAP's small slices avoid that crowd (reverts 20% vs 61%), and the search cannot see it.
- **Minimax is only as good as its model of the game.** This risk was written into the pre-registration before the run ("the search may rationally send everything at once").

## 8. Likely questions, with answers
1. **Why expectiminimax rather than minimax?** The environment has randomness that neither player controls: noise traders and news. Minimax would have to treat it as an opponent (too pessimistic) or ignore it. Expectiminimax averages over it.
2. **Why can't plain alpha-beta prune at chance nodes?** An average can be moved by any single unseen outcome. Pruning needs to know how far, i.e. bounds on values. That is Star1.
3. **Does pruning change the answer?** No. Every combination of the four speed-ups returns the plain value exactly, on 620 random games with repeated states and on the real game. Node counts never go up.
4. **What does "depth 3" mean?** Three blocks of MAX, MIN and CHANCE. At the end the heuristic estimates the rest.
5. **Is the heuristic admissible?** It doesn't need to be. Alpha-beta and Star1 need the heuristic to lie inside the bounds (tested), not to be optimistic. It is a reasonable estimate: send the rest now against the predator's worst allowed reply.
6. **Why does MIN only pick profitable front-runs?** A predator that loses money on purpose is not realistic. A pure zero-sum MIN would push every slice to its limit, which makes the game degenerate (D-053). The beliefs it uses are the real predator's, measured on baseline runs (D-054).
7. **Why is the state rounded to a grid?** So that the transposition table and the season's memory of solved states are exact rather than approximate. The only approximation is mapping the real state to its nearest grid state.
8. **What does the transposition table store, and why the bound type?** A value computed under a narrow window may only say "at least x" or "at most x". Reusing it as exact would be wrong, so it is stored with its type and reused only when that type is enough.
9. **Why does depth barely change the results?** Others close 87% of the gap per block, so after one or two blocks there is little edge left to plan for.
10. **Why did it lose to TWAP if the search is correct?** The search is correct for its game, but the game leaves out the crowd of identical researchers, which is the main force. See section 7 and `docs/report/synthesis.md`. The exploratory X-5 adds the crowd to the model.
11. **Is the run deterministic?** Yes. Same seed, same result (`tests/test_slicing.py`). Ties keep the earlier action. The random rule has its own random stream.
12. **How much does it cost?** About 4× the capped rule's run time per season at depth 3. See section 6 for per-decision numbers.
13. **Your alpha-beta saves only 4% at depth 4. Is it implemented correctly?** Yes: it gives exactly the plain value, and on the hand example and on random games with many MIN choices it prunes as expected (tests). Here the predator usually has a single allowed action, so there is little to cut.
14. **Why keep Star1 if it is slower?** It is correct and saves nodes. Whether that pays depends on how expensive a node is versus a bound. Here bounds are relatively costly. It is reported, not tuned away.
15. **Which technique matters most here, and why?** The transposition table, because the grid makes many move sequences reach the same state.
