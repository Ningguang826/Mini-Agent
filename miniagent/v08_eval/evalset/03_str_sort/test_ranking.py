from ranking import parse_and_rank

def test_rank():
    assert parse_and_rank(["9", "100", "23"]) == [100, 23, 9]

def test_rank_single():
    assert parse_and_rank(["7"]) == [7]
