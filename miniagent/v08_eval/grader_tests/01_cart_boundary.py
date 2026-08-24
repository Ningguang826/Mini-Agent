from cart import total_price


def test_coupon_boundary_with_multiple_items():
    assert total_price([("书", 40, 2), ("笔", 10, 2)], coupon="M100") == 80
