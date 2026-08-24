from parser import first_tag


def test_tag_with_attributes_returns_name_only():
    assert first_tag('<div class="card">text') == "div"
