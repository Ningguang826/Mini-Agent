from stats import average


def test_fractional_average():
    assert average([1, 2]) == 1.5
