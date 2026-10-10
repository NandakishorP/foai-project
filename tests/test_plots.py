"""Chart helpers."""


def test_none_parameter_values_are_labelled_all() -> None:
    from tfs.experiments.plots import _fmt

    assert _fmt(None) == "all" and _fmt(2.0) == "2"
