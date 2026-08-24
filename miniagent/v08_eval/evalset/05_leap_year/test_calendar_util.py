from calendar_util import is_leap

def test_common_leap():
    assert is_leap(2024) is True

def test_century_not_leap():
    assert is_leap(1900) is False

def test_400_leap():
    assert is_leap(2000) is True

def test_common_year():
    assert is_leap(2023) is False
