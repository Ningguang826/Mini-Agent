from ranking import parse_and_rank


def test_negative_and_duplicate_scores():
    assert parse_and_rank(["-1", "10", "10"]) == [10, 10, -1]
