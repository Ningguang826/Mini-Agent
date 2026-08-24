"""MiniAgent v0.0 —— 还不会说话的 REPL 骨架。

第 2 章把 echo 换成真正的模型调用，它就活了。
"""


def main() -> None:
    print("MiniAgent v0.0（还不会说话），输入 exit 退出")
    while True:
        try:
            user_input = input("\n你> ").strip()
        except EOFError:
            break
        if not user_input or user_input == "exit":
            break
        print(f"MiniAgent> 你刚才说：{user_input}")


if __name__ == "__main__":
    main()
