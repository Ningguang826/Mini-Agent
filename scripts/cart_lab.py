#!/usr/bin/env python3
r"""Prepare or reset the reproducible cart bug lab used by chapter 4.

舞台三件套（教师用），都建在仓库根目录下，scripts/ 里只放本脚本：
  fixtures/cart_boundary/starter/cart.py      —— 带 bug 的购物车（母版）
  fixtures/cart_boundary/starter/test_cart.py —— 3 条测试（母版）
  labs/cart_boundary/                         —— 练习目录（由本脚本从 starter 拷贝生成，reset 可反复重建）

目录关系（fixtures 与 labs 是兄弟目录，都在仓库根 REPO 下）：
  F:\MiniAgent\                        ← REPO（仓库根）
  ├─ fixtures\cart_boundary\starter\   ← STARTER（母版，人工维护，不要在练习时改它）
  ├─ labs\cart_boundary\               ← LAB（练习目录，学生/agent 在这里动手）
  └─ scripts\cart_lab.py               ← 本脚本；运行入口而已

执行命令（在仓库根目录）：
  python scripts/cart_lab.py reset     # 删掉旧练习目录，从 starter 全新拷贝（起点永远确定）
  python scripts/cart_lab.py prepare   # 只在练习目录不存在时创建；已存在则报错，防误覆写
  cd labs/cart_boundary && python -m pytest -q   # 进练习目录跑测试（见 test_cart.py 注释）



为什么用 reset 而不是手动改文件：母版在 fixtures 里保持干净，每次 reset 重拷贝，
保证每次实验的起点（bug 内容 + 测试状态）完全一致、可复现。
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


# REPO：仓库根目录。__file__ 是本脚本路径，parents[1] 从 scripts/ 往上一层,到仓库根目录
REPO = Path(__file__).resolve().parents[1]
STARTER = REPO / "fixtures" / "cart_boundary" / "starter"   # 母版目录（不要改这里，改了会影响所有 reset）
LAB = REPO / "labs" / "cart_boundary"                       # 练习目录（学生/agent 在这里动手）


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["prepare", "reset"])
    args = parser.parse_args()

    if LAB.exists():
        if args.action == "prepare":
            raise SystemExit(f"练习目录已存在：{LAB}；需要重置时运行 reset")
        # rmtree：递归删除整个练习目录
        # 注意：rmtree 只服务于"LAB 已存在"的 reset 路径
        # 目录已存在时直接 copytree 会 FileExistsError，先 rmtree 才能让前提重新成立。
        shutil.rmtree(LAB)
        # "rmtree 清场 → mkdir 建父目录 → copytree 灌模板"：
        # 这是所有"可反复恢复的实验环境"的通用套路（虚拟机快照、docker volume、git clone 都是这个模式的工程版）

    
    LAB.parent.mkdir(exist_ok=True) ## mkdir(exist_ok=True)：labs/ 存在就跳过，不存在就创建
    # copytree：把母版目录树整体复制为练习目录；要求 dst 不存在（即LAB），才会自动创建它及所需父目录
    shutil.copytree(STARTER, LAB)   # 从母版全新拷贝，起点回到带 bug 的原始状态
    print(f"购物车练习已准备：{LAB}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
