import numpy as np

from tfs.core.rng import RngFactory


def test_same_seed_same_stream() -> None:
    a = RngFactory(7).stream("noise_main", market=3, index=1).random(5)
    b = RngFactory(7).stream("noise_main", market=3, index=1).random(5)
    np.testing.assert_array_equal(a, b)


def test_different_keys_give_different_streams() -> None:
    f = RngFactory(7)
    base = f.stream("noise_main", 0, 0).random(5)
    assert not np.array_equal(base, f.stream("noise_main", 0, 1).random(5))
    assert not np.array_equal(base, f.stream("noise_main", 1, 0).random(5))
    assert not np.array_equal(base, f.stream("noise_ref", 0, 0).random(5))
    assert not np.array_equal(base, RngFactory(8).stream("noise_main", 0, 0).random(5))


def test_streams_do_not_depend_on_creation_order() -> None:
    """Common random numbers: creating extra streams first changes nothing."""
    f1 = RngFactory(11)
    first = f1.stream("private", 0, 2).random(3)

    f2 = RngFactory(11)
    f2.stream("predator", 0, 0).random(100)  # a new component added in another condition
    f2.stream("private", 0, 0).random(100)
    second = f2.stream("private", 0, 2).random(3)

    np.testing.assert_array_equal(first, second)
