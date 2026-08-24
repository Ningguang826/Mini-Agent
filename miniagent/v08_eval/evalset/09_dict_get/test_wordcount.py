from wordcount import count_words

def test_count():
    assert count_words(["a", "b", "a"]) == {"a": 2, "b": 1}

def test_empty():
    assert count_words([]) == {}
