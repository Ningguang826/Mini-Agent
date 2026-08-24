from parser import first_tag

def test_single():
    assert first_tag("<div>hello") == "div"

def test_multiple_tags():
    assert first_tag("<a><b>") == "a"  # 贪婪匹配会吃成 "a><b"

def test_none():
    assert first_tag("no tags") is None
