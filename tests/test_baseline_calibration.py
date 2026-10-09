"""The D-029 selection rule, tested on hand-made grids (no simulation)."""

from tfs.experiments.baseline_calibration import GridPoint, select


def _g(rho: float, cap: float, part: float, share: float) -> GridPoint:
    return GridPoint(rho, cap, 1.0, 1.0, 1.0, part, share, 0.0, 1.0)


def test_prefers_smallest_rho_then_capital_then_participation_near_60() -> None:
    grid = [
        _g(0.9, 1.0, 0.60, 0.7),
        _g(0.5, 4.0, 0.60, 0.7),
        _g(0.5, 2.0, 0.68, 0.7),
        _g(0.5, 2.0, 0.58, 0.7),  # <- smallest rho, smallest capital among feasible, closest to 60%
        _g(0.25, 1.0, 0.60, 0.5),  # infeasible: share too low
        _g(0.0, 1.0, 0.45, 0.9),  # infeasible: participation out of band
    ]
    choice, reason = select(grid)
    assert choice == grid[3]
    assert "feasible" in reason and "FALLBACK" not in reason


def test_fallback_takes_highest_share_in_band() -> None:
    grid = [_g(0.5, 1.0, 0.55, 0.40), _g(1.0, 4.0, 0.65, 0.55), _g(1.0, 4.0, 0.80, 0.95)]
    choice, reason = select(grid)
    assert choice == grid[1]
    assert reason.startswith("FALLBACK")


def test_nothing_in_band() -> None:
    choice, _ = select([_g(0.5, 1.0, 0.2, 0.9)])
    assert choice is None
