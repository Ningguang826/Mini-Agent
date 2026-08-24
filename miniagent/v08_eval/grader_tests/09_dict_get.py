from wordcount import count_words


def test_repeated_unicode_words():
    assert count_words(["猫", "猫", "狗"]) == {"猫": 2, "狗": 1}
