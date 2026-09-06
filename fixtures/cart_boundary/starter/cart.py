# fixtures/cart_boundary/starter/cart.py
# 舞台背景：购物车总价的优惠券优惠逻辑。为"满 100 减 20"准备的优惠券，却写到 total > 100，
# 导致"正好 100"的情况被漏掉 —— 这就是边界 off-by-one bug 的典型形态。
# 修复方向（教学练习目标）：cart.py 中的 total > 100 应该改为 total >= 100。

def total_price(items, coupon=None):
    """items: [(名称, 单价, 数量)]。优惠券 M100：满 100 减 20。"""
    total = sum(price * count for _, price, count in items)   # 各行小计求和
    if coupon == "M100" and total > 100:   # ← BUG 在这：满 100 应包含等于 100 的情况，应写 >= 而非 >
        total -= 20
    return total
