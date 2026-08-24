from paging import get_page

def test_first_page():
    assert get_page([1, 2, 3, 4, 5], 0, 2) == [1, 2]

def test_last_partial_page():
    assert get_page([1, 2, 3, 4, 5], 2, 2) == [5]

def test_out_of_range():
    assert get_page([1, 2], 5, 2) == []
