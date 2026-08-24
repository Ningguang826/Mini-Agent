from collector import add_item


def test_explicit_bucket_is_still_reused():
    bucket = []
    assert add_item("a", bucket) is bucket
