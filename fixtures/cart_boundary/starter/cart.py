def total_price(items, coupon=None):
    """items: [(名称, 单价, 数量)]。优惠券 M100：满 100 减 20。"""
    total = sum(price * count for _, price, count in items)
    if coupon == "M100" and total > 100:
        total -= 20
    return total
