from collector import add_item

def test_with_bucket():
    b = ["x"]
    assert add_item("y", b) == ["x", "y"]

def test_fresh_bucket_each_call():
    assert add_item("a") == ["a"]
    assert add_item("b") == ["b"]  # 第二次调用不该带着上一次的残留
