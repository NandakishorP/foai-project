"""Dashboard (D-062): data are deterministic, fallbacks exist, and every page renders without errors."""

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
streamlit_testing = pytest.importorskip("streamlit.testing.v1", reason="dashboard extra not installed")

VIEWS = ["act1", "act2", "act3", "act4", "verdicts"]


@pytest.fixture(autouse=True)
def _restore_main_module():
    """AppTest runs its script as __main__. Restore the real one afterwards, or later tests that start
    worker processes (which re-import __main__ under 'spawn') would import the app script instead."""
    import sys

    main = sys.modules["__main__"]
    yield
    sys.modules["__main__"] = main


def _render(view: str) -> None:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path.cwd() / "dashboard"))
    import views

    getattr(views, view)()


def _app():
    at = streamlit_testing.AppTest.from_file(str(ROOT / "dashboard" / "app.py"), default_timeout=120)
    at.run()
    return at


def test_landing_page_renders() -> None:
    at = _app()
    assert not at.exception, at.exception
    assert any("Demo, in order" in s.value for s in at.subheader)


@pytest.mark.parametrize("view", VIEWS)
def test_every_view_renders(view: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(ROOT)
    at = streamlit_testing.AppTest.from_function(_render, args=(view,), default_timeout=120)
    at.run()
    assert not at.exception, at.exception


def test_committed_data_reproduce_the_archived_front_run() -> None:
    """Block 23 of the replay market is the archived Phase 2a front-run (D-036)."""
    block = json.loads((ROOT / "dashboard/data/replay.json").read_text())["blocks"][23]
    decision = block["decisions"]["predator_0"]
    assert decision["victim"] == "forecaster_5" and round(decision["shares"], 1) == 15.0
    assert round(block["before"], 4) == 0.5425 and round(block["after"], 4) == 0.6963


def test_every_fallback_figure_exists() -> None:
    names = {p.name for p in (ROOT / "dashboard/fallback").glob("*.png")}
    for prefix in ("0_", "1a_", "2_", "3_", "4a_", "4b_", "4c_", "5_"):
        assert any(n.startswith(prefix) for n in names), prefix


def _view(view: str, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(ROOT)
    at = streamlit_testing.AppTest.from_function(_render, args=(view,), default_timeout=120)
    at.run()
    return at


def test_every_shock_scenario_renders(monkeypatch: pytest.MonkeyPatch) -> None:
    at = _view("act1", monkeypatch)
    for option in at.selectbox[0].options:
        at.selectbox[0].select(option).run()
        assert not at.exception, (option, at.exception)


@pytest.mark.parametrize("depth", [1, 2])
def test_real_game_trees_render(depth: int, monkeypatch: pytest.MonkeyPatch) -> None:
    at = _view("act4", monkeypatch)
    for option in [o for o in at.selectbox[0].options if o.startswith("Real")]:
        at.selectbox[0].select(option).run()
        at.radio[0].set_value(depth).run()
        assert not at.exception, (option, at.exception)
