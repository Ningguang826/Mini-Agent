from calendar_util import is_leap


def test_non_400_century():
    assert is_leap(2100) is False
