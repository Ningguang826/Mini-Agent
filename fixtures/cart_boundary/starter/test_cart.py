from cart import total_price


def test_no_coupon():
    assert total_price([("苹果", 5, 2)]) == 10


def test_coupon_over_100():
    assert total_price([("键盘", 120, 1)], coupon="M100") == 100


def test_coupon_exact_100():
    assert total_price([("耳机", 100, 1)], coupon="M100") == 80
