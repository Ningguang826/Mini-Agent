from batches import batch_sums


def test_three_independent_batches():
    assert batch_sums([[1], [2, 3], [-1]]) == [1, 5, -1]
