from batches import batch_sums

def test_two_batches():
    assert batch_sums([[1, 2], [3]]) == [3, 3]

def test_empty_batch():
    assert batch_sums([[], [5]]) == [0, 5]
