"""MiniAgent v0.2 —— 第一次让模型"动手"：单轮工具调用。

完整的四步往返：
  1. 把用户请求 + 工具说明书发给模型
  2. 模型回复"我想调这些工具"（tool_calls）
  3. 我们的代码真正执行工具，把结果作为 tool 消息追加
  4. 再发给模型，它基于结果给出最终回答

局限（故意留的）：只支持一轮工具调用。"读文件→改文件→跑测试"
这种多步任务它做不完——这就是 v0.3 Agent Loop 要解决的问题。
"""

import json
import os
import sys
from pathlib import Path

from openai import OpenAI

from tools import TOOL_SCHEMAS, execute_tool_call


def load_api_key() -> str:
    if key := os.environ.get("DEEPSEEK_API_KEY"):
        return key
    env_file = Path(__file__).resolve().parents[2] / ".env"
    for line in env_file.read_text().splitlines():
        if line.startswith("DEEPSEEK_API_KEY="):
            return line.split("=", 1)[1].strip()
    sys.exit("没有找到 DEEPSEEK_API_KEY")


client = OpenAI(api_key=load_api_key(), base_url="https://api.deepseek.com")
MODEL = "deepseek-v4-flash"

SYSTEM_PROMPT = (
    "你是 MiniAgent，一个命令行助手。"
    "你可以调用工具来读写文件、执行命令，工具结果会返回给你。"
)


def main() -> None:
    task = " ".join(sys.argv[1:]) or input("任务> ").strip()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task},
    ]

    # 第 1 步：带着工具说明书请求模型
    response = client.chat.completions.create(
        model=MODEL, messages=messages, tools=TOOL_SCHEMAS
    )
    message = response.choices[0].message

    if not message.tool_calls:
        print(message.content)
        return

    # 第 2 步：模型说了它想调什么。注意 assistant 消息必须原样进历史
    messages.append(message)

    # 第 3 步：真正执行的是我们的代码，不是模型
    for call in message.tool_calls:
        name = call.function.name
        try:
            args = json.loads(call.function.arguments)
        except json.JSONDecodeError:
            args = call.function.arguments
        print(f"[工具] {name}({args})")
        result = execute_tool_call(name, call.function.arguments)
        print(f"[结果] {result[:200]}")
        messages.append(
            {"role": "tool", "tool_call_id": call.id, "content": result}
        )

    # 第 4 步：把结果发回去，拿最终回答
    final = client.chat.completions.create(model=MODEL, messages=messages)
    print(f"\nMiniAgent> {final.choices[0].message.content}")


if __name__ == "__main__":
    main()
