"""MiniAgent v0.1 —— 记得住对话的终端聊天程序。

核心只有一件事：所谓"多轮对话"，就是把历史 messages 数组原样重发。
"""

import os
import sys
from pathlib import Path

from openai import OpenAI


def load_api_key() -> str:
    """优先读环境变量，其次读仓库根目录的 .env。"""
    if key := os.environ.get("DEEPSEEK_API_KEY"):
        return key
    env_file = Path(__file__).resolve().parents[2] / ".env"
    for line in env_file.read_text().splitlines():
        if line.startswith("DEEPSEEK_API_KEY="):
            return line.split("=", 1)[1].strip()
    sys.exit("没有找到 DEEPSEEK_API_KEY，请配置环境变量或仓库根目录的 .env")


client = OpenAI(api_key=load_api_key(), base_url="https://api.deepseek.com")
MODEL = "deepseek-v4-flash"

SYSTEM_PROMPT = "你是 MiniAgent，一个简洁直接的中文助手。"


def chat(messages: list[dict]) -> str:
    """流式调用模型，边收边打印，返回完整回复文本。"""
    stream = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        stream=True,
    )
    reply = ""
    for chunk in stream:
        delta = chunk.choices[0].delta
        if delta and delta.content:
            print(delta.content, end="", flush=True)
            reply += delta.content
    print()
    return reply


def main() -> None:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    print(f"MiniAgent v0.1（{MODEL}），输入 exit 退出")
    while True:
        try:
            user_input = input("\n你> ").strip()
        except EOFError:
            break
        if not user_input or user_input == "exit":
            break
        messages.append({"role": "user", "content": user_input})
        print("MiniAgent> ", end="", flush=True)
        reply = chat(messages)
        # 不把回复追加回去，模型下一轮就会"失忆"——这行是全章的核心
        messages.append({"role": "assistant", "content": reply})


if __name__ == "__main__":
    main()
