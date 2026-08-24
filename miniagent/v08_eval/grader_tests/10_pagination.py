from paging import get_page


def test_middle_page():
    assert get_page([1, 2, 3, 4, 5], 1, 2) == [3, 4]
