# fixtures/cart_boundary/starter/test_cart.py
# 三条测试分别覆盖三种情况：普通值 / 超过阈值的正常值 / 正好压线（边界）值 —— 这是测试设计的标配。
# pytest 自动发现规则：文件名以 test_ 开头的 .py，其中 def test_ 开头的函数是单独一个用例。
#
# 执行（在 labs/cart_boundary 目录下，即 reset 后的练习目录里）：
#   python -m pytest -q
#
# 输出怎么读：-q（quiet）模式下三行测试按声明顺序各打一个字符：
#   .   = 通过（passed）
#   F   = 断言失败（failed）：assert 100 == 80 —— 左边是函数实际返回 100，右边是测试期望 80
#   E   = 出错（error）：用例还没跑到断言就炸了（如 import 失败），又跟 F 不同
# 挂掉的那条随后会展示：FAILED test_cart.py::test_coupon_exact_100
#   —— "文件名::测试函数名"，:: 是 pytest 分隔文件与用例的符号
# 修复 bug 后再跑应该看到 "..."（三个点全过）。

from cart import total_price     # 被测函数；pytest 会把当前目录加入 sys.path 使本地 import 可用


def test_no_coupon():
    # 普通值：2 × 5 = 10，无券 → 应返回 10
    assert total_price([("苹果", 5, 2)]) == 10


def test_coupon_over_100():
    # 超过阈值：120 > 100，减 20 → 应返回 100
    assert total_price([("键盘", 120, 1)], coupon="M100") == 100


def test_coupon_exact_100():
    # 边界值：正好 100 也应触发满减。当前代码写的是 > 而非 >=，所以减不掉。
    # 输出：assert 100 == 80（左 = 函数实际返回，右 = 测试声明的正确值）
    assert total_price([("耳机", 100, 1)], coupon="M100") == 80
