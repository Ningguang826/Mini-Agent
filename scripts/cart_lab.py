#!/usr/bin/env python3
"""Prepare or reset the reproducible cart bug lab used by chapter 4."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
STARTER = REPO / "fixtures" / "cart_boundary" / "starter"
LAB = REPO / "labs" / "cart_boundary"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["prepare", "reset"])
    args = parser.parse_args()

    if LAB.exists():
        if args.action == "prepare":
            raise SystemExit(f"练习目录已存在：{LAB}；需要重置时运行 reset")
        shutil.rmtree(LAB)
    LAB.parent.mkdir(exist_ok=True)
    shutil.copytree(STARTER, LAB)
    print(f"购物车练习已准备：{LAB}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
