from stats import average

def test_normal():
    assert average([2, 4]) == 3.0

def test_empty():
    assert average([]) == 0.0
